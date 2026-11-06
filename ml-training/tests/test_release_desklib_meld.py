"""release_desklib_meld: the MELD soup stored as one stacked LoRA adapter equals the average of its members."""

import json

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("peft")

import release_desklib_meld as release  # noqa: E402
from test_soup_meld_lora import Meld, saved_adapter  # noqa: E402


def test_stacked_adapter_update_is_the_members_average(tmp_path):
    torch.manual_seed(0)
    model = Meld()
    expected = [saved_adapter(model, tmp_path / f"m{s}", seed=s) for s in (1, 2, 3)]

    stacked = release.stacked_soup_adapter([tmp_path / f"m{s}" for s in (1, 2, 3)], tmp_path / "soup", torch.float32)

    config = json.loads((stacked / "adapter_config.json").read_text())
    assert config["r"] == 6 and config["lora_alpha"] == 6
    got = release.lora_deltas(model, stacked)
    for name in ("Wqkv", "Wo"):
        want = sum(e[name] for e in expected) / 3
        assert torch.allclose(got[name], want, atol=1e-6)
    assert release.check_stacked(model, [tmp_path / f"m{s}" for s in (1, 2, 3)], stacked) < 1e-6


def test_stacked_adapter_gives_the_averaged_output_when_merged(tmp_path):
    from peft import PeftModel

    torch.manual_seed(0)
    model = Meld()
    members = [tmp_path / f"m{s}" for s in (1, 2)]
    deltas = [saved_adapter(model, m, seed=s) for s, m in zip((1, 2), members)]
    base = {n: model.backbone.get_submodule(n).weight.detach().clone() for n in ("Wqkv", "Wo")}
    release.stacked_soup_adapter(members, tmp_path / "soup", torch.float16)

    merged = PeftModel.from_pretrained(model.backbone, str(tmp_path / "soup")).merge_and_unload()
    x = torch.randn(4, 8)
    for name in ("Wqkv", "Wo"):
        want = x @ (base[name] + (deltas[0][name] + deltas[1][name]) / 2).t()
        assert torch.allclose(merged.get_submodule(name)(x), want, atol=1e-2)  # fp16-stored factors


def test_members_with_different_targets_are_refused(tmp_path):
    from peft import LoraConfig, get_peft_model

    torch.manual_seed(0)
    model = Meld()
    saved_adapter(model, tmp_path / "a", seed=1)
    wrapped = get_peft_model(model.backbone, LoraConfig(r=2, lora_alpha=4, target_modules=["Wo"]))
    wrapped.save_pretrained(tmp_path / "b")
    model.backbone = wrapped.unload()

    with pytest.raises(SystemExit, match="different modules"):
        release.stacked_soup_adapter([tmp_path / "a", tmp_path / "b"], tmp_path / "soup")
