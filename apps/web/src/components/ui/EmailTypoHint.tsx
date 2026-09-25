import FormNotice from "./FormNotice";
import RowAction from "./RowAction";

interface EmailTypoHintProps {
  suggestion: string | null;
  onUse: () => void;
  onKeep: () => void;
}

export default function EmailTypoHint({
  suggestion,
  onUse,
  onKeep,
}: EmailTypoHintProps) {
  if (!suggestion) return null;
  return (
    <FormNotice tone="info" id="add-email-hint" role="status">
      <span className="flex flex-wrap items-center gap-x-3">
        <span>
          Did you mean{" "}
          <span className="font-mono text-foreground">{suggestion}</span>?
        </span>
        <span className="flex gap-1">
          <RowAction onClick={onUse}>Use suggestion</RowAction>
          <RowAction onClick={onKeep}>Keep as typed</RowAction>
        </span>
      </span>
    </FormNotice>
  );
}
