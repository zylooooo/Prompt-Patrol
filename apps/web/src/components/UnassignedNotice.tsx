export default function UnassignedNotice({
  className = "",
}: {
  className?: string;
}) {
  return (
    <section
      className={`shrink-0 rounded-xl bg-surface p-12 text-center shadow-md ${className}`.trimEnd()}
    >
      <p className="text-lg font-medium text-foreground">
        You are not assigned to an instructor yet.
      </p>
      <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
        Once an instructor adds you as their teaching assistant, you can screen
        answers for their courses. Ask them to add you, or contact your course
        administrator.
      </p>
    </section>
  );
}
