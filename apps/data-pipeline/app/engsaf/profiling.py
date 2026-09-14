import json
import logging
import re

import ftfy
import pandas as pd
from ftfy import TextFixerConfig

from engsaf.loader import OUTPUT_PATH

logger = logging.getLogger(__name__)

REPORT_PATH = OUTPUT_PATH.parent.parent / "engsaf_profile_report.json"

TEXT_COLUMNS = ["question", "student_answer", "reference_answer"]

_ENCODING_ARTIFACT_CONFIG = TextFixerConfig(uncurl_quotes=False)

IN_SCOPE_QUESTIONS = {
    "Q1. State TRUE or FALSE and justify. No correct justification, no marks. e. If a parent process forks a new child process, the exec system call cannot be used in the parent process until the child process terminates.",
    "c. Assume the OS is using a lazy allocation policy for memory allocation to processes. On a page fault due to an unmapped physical page(and a valid virtual address), the OS handles the page fault (via allocation and updates to the virtual to physical address mappings in the page table) and then executes the next instruction (the one after the faulting instruction).",
    "a. List and explain two privileged actions that an user process may attempt to perform and which are prevented by the OS via the limited-directed execution setup. Note that the user process has to know specifically how to make such an attempt. (e.g., the user process does not know that a PCB exists and hence may not know how to update its contents).",
    "Two advantages of separating declaration from definition are: .....",
    "Q1. State TRUE or FALSE and justify. No correct justification, no marks. d. Without the timer interrupt, the OS still has opportunities to schedule READY processes and share the CPU for multitasking",
    "Q1. State TRUE or FALSE and justify. No correct justification, no marks. e. If a parent process forks a new child process, the exec system call can be used in the parent process before the child process terminates.",
    "Q1. State TRUE or FALSE and justify. No correct justification, no marks. a. The pipe system call creates two file descriptors fd[0] and fd[1]. Writes using fd[1] can be read using fd[0] but not vice-versa.",
    "Q1. State TRUE or FALSE and justify. No correct justification, no marks. d. Assuming an user process knows the PID of another task from a pool of several READY processes, it does not have the capability to initiate a context switch and schedule the target process next on the CPU.",
    "Define Priority Inversion in single line.",
    "Q1. State TRUE or FALSE and justify. No correct justification, no marks. c. A process executing on the CPU is interrupted due to an interrupt. This process is always rescheduled immediately (and control returns back to the paused process) on completion of the interrupt handler to prevent any data loss.",
    "Q1. State TRUE or FALSE and justify. No correct justification, no marks. b. Assuming an user process knows the PID of another target process (from a pool of several READY processes), it has the capability to initiate a context switch and schedule the target process next on the CPU.",
    "Q1. State TRUE or FALSE and justify. No correct justification, no marks. a. The pipe system call creates two file descriptors fd[0] and fd[1]. Writes using fd[0] can be read using fd[0] or vice-versa (read on fd[1] and write on fd[0]).",
    "Q1. State TRUE or FALSE and justify. No correct justification, no marks. c. Without the timer interrupt, the OS has no opportunities to schedule READY processes and share the CPU for multitasking.",
    "Q1. State TRUE or FALSE and justify. [6 marks] No correct justification, no marks. d. An executable (binary) program can be used to instantiate and execute more than one process simuitaneous.y. In such a situation, processes of the same program use the same PCB process-conro.Dock, with a reference counter to indicate number of instances,",
    "Q1. State TRUE or FALSE and justify. No correct justification, no marks. b. A process executing on the CPU is interrupted due to an interrupt. This process may not be scheduled immediately on completion of the interrupt handler.",
    "c. When the fork() system call is made the child process is (almost) identical to the parent process. In the parent process, the return path from kernel mode to user mode happens via the trap/interrupt handler (system call is a trap/interrupt). Explain the return path from the kernel mode to the user mode for the child process. Specifically, there was no trap in the child process, so how does the child process return from a trap?",
    "Q1. State TRUE or FALSE and justify. [6 marks] No correct justification, no marks. a. Since the OS knows that it executes on a CPU and interacts with IO devices via the CPU, the instruction set architecture is not an abstraction provided by the CPU to the OS.",
    "Q1. State TRUE or FALSE and justify. [6 marks] No correct justification, no marks. f. A spinlock is called a spinlock, as each attempt to acquire the lock will need spinning on the CPU (checking for lock status more than once), before the lock can be acquired.",
}


def _normalize_question(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def is_in_scope(question: str) -> bool:
    return _normalize_question(question) in IN_SCOPE_QUESTIONS


def _rows_matching(df: pd.DataFrame, predicate) -> pd.DataFrame:
    mask = pd.Series(False, index=df.index)
    for col in TEXT_COLUMNS:
        mask |= df[col].apply(predicate)
    return df[mask]


def _has_encoding_artifact(text) -> bool:
    if not isinstance(text, str):
        return False
    text = text.replace("\r\n", "\n")
    return ftfy.fix_text(text, config=_ENCODING_ARTIFACT_CONFIG) != text


def _is_blank(text) -> bool:
    return isinstance(text, str) and text.strip() == ""


def profile(df: pd.DataFrame) -> dict:
    dup_rows = df[df.duplicated(subset=["question", "student_answer"], keep=False)]
    encoding_artifact_rows = _rows_matching(df, _has_encoding_artifact)
    blank_rows = _rows_matching(df, _is_blank)
    missing_rows = df[df[TEXT_COLUMNS].isna().any(axis=1)]
    out_of_scope_rows = df[~df["question"].apply(is_in_scope)]

    return {
        "row_count": len(df),
        "duplicate_answer_ids": sorted(dup_rows["id"].tolist()),
        "encoding_artifact_ids": sorted(encoding_artifact_rows["id"].tolist()),
        "blank_text_ids": sorted(blank_rows["id"].tolist()),
        "missing_text_ids": sorted(missing_rows["id"].tolist()),
        "out_of_scope_question_ids": sorted(out_of_scope_rows["question_id"].unique().tolist()),
        "out_of_scope_ids": sorted(out_of_scope_rows["id"].tolist()),
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    df = pd.read_parquet(OUTPUT_PATH)
    report = profile(df)

    for key, value in report.items():
        if isinstance(value, list):
            logger.info("%s: %d", key, len(value))
        else:
            logger.info("%s: %s", key, value)

    REPORT_PATH.write_text(json.dumps(report, indent=2))
    logger.info("Wrote report -> %s", REPORT_PATH)


if __name__ == "__main__":
    main()
