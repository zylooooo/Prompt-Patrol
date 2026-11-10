"""soup_meld_lora: the weight change it reads from an adapter, and how heads are averaged."""

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("peft")

import soup_meld_lora  # noqa: E402


class Backbone(torch.nn.Module):
    """Two layers named like ModernBERT's, which is all the LoRA targets need."""

    def __init__(self):
        super().__init__()
        self.Wqkv = torch.nn.Linear(8, 24, bias=False)
        self.Wo = torch.nn.Linear(8, 8, bias=False)


class Meld(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.backbone = Backbone()


def saved_adapter(model, path, seed):
    """An adapter with non-zero B (PEFT starts B at zero, which would make every update zero)."""
    from peft import LoraConfig, get_peft_model

    torch.manual_seed(seed)
    wrapped = get_peft_model(model.backbone, LoraConfig(r=2, lora_alpha=4, target_modules=["Wqkv", "Wo"]))
    for name, param in wrapped.named_parameters():
        if "lora_B" in name:
            torch.nn.init.normal_(param)
    expected = {n: wrapped.get_submodule(f"base_model.model.{n}").get_delta_weight("default").detach().clone()
                for n in ("Wqkv", "Wo")}
    wrapped.save_pretrained(path)
    model.backbone = wrapped.unload()
    return expected


def test_lora_deltas_reads_the_merged_update_and_leaves_the_backbone_unchanged(tmp_path):
    torch.manual_seed(0)
    model = Meld()
    before = {k: v.clone() for k, v in model.backbone.state_dict().items()}
    expected = saved_adapter(model, tmp_path / "a", seed=1)

    deltas = soup_meld_lora.lora_deltas(model, tmp_path / "a")

    assert sorted(deltas) == ["Wo", "Wqkv"]
    for name, delta in deltas.items():
        assert delta.shape == model.backbone.get_submodule(name).weight.shape
        assert torch.allclose(delta, expected[name], atol=1e-6)
    assert type(model.backbone) is Backbone
    after = model.backbone.state_dict()
    assert sorted(after) == sorted(before)
    assert all(torch.equal(before[k], after[k]) for k in before)


def test_adding_the_delta_gives_the_same_output_as_the_adapter(tmp_path):
    from peft import PeftModel

    torch.manual_seed(0)
    model = Meld()
    saved_adapter(model, tmp_path / "a", seed=1)
    x = torch.randn(3, 8)
    with_adapter = PeftModel.from_pretrained(model.backbone, tmp_path / "a")
    with torch.no_grad():
        want = {n: with_adapter.base_model.model.get_submodule(n)(x) for n in ("Wqkv", "Wo")}
    model.backbone = with_adapter.unload()

    with torch.no_grad():
        for name, delta in soup_meld_lora.lora_deltas(model, tmp_path / "a").items():
            model.backbone.get_submodule(name).weight += delta
        for name, out in want.items():
            assert torch.allclose(model.backbone.get_submodule(name)(x), out, atol=1e-5)


def test_average_heads_averages_floats_and_keeps_equal_masks():
    heads = [{"proto": torch.tensor([1.0, 3.0]), "mask": torch.tensor([True, False])},
             {"proto": torch.tensor([3.0, 5.0]), "mask": torch.tensor([True, False])}]
    out = soup_meld_lora.average_heads(heads)
    assert out["proto"].tolist() == [2.0, 4.0]
    assert out["mask"].tolist() == [True, False]


def test_average_heads_refuses_masks_that_differ():
    heads = [{"mask": torch.tensor([True])}, {"mask": torch.tensor([False])}]
    with pytest.raises(SystemExit, match="differs"):
        soup_meld_lora.average_heads(heads)
