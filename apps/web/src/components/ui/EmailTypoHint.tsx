import FormNotice from "./FormNotice";
import RowAction from "./RowAction";

interface EmailTypoHintProps {
  suggestion: string | null;
  onUse: () => void;
}

export default function EmailTypoHint({
  suggestion,
  onUse,
}: EmailTypoHintProps) {
  if (!suggestion) return null;
  return (
    <FormNotice tone="info" id="add-email-hint" role="status">
      <span className="flex flex-wrap items-center gap-x-3">
        <span>
          Did you mean{" "}
          <span className="font-mono text-foreground">{suggestion}</span>?
        </span>
        <RowAction onClick={onUse}>Use suggestion</RowAction>
      </span>
    </FormNotice>
  );
}
