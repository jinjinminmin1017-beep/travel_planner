import type { ChallengeResult } from "./contracts.js";

export class WorkerSearchError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly retryable: boolean,
    readonly challenge?: ChallengeResult,
  ) {
    super(message);
    this.name = "WorkerSearchError";
  }
}

export function stableError(error: unknown): WorkerSearchError {
  if (error instanceof WorkerSearchError) {
    return error;
  }
  if (error instanceof Error && error.name === "TimeoutError") {
    return new WorkerSearchError("WORKER_TIMEOUT", "airline response timed out", true);
  }
  return new WorkerSearchError("WORKER_INTERNAL_ERROR", "browser search failed", true);
}
