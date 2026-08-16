import type { ErrorResponse } from "../types";

export class ApiRequestError extends Error {
  readonly errorCode: string;
  readonly details: Record<string, unknown> | null;
  readonly retryable: boolean;

  constructor(response: ErrorResponse) {
    super(buildApiErrorMessage(response));
    this.name = "ApiRequestError";
    this.errorCode = response.error_code;
    this.details = response.details;
    this.retryable = response.retryable;
  }
}

export function buildApiErrorMessage(response: Pick<ErrorResponse, "message" | "user_visible_message" | "details">): string {
  const message = response.user_visible_message?.trim() || response.message?.trim() || "请求失败";
  const question = firstFollowUpQuestion(response.details);
  if (!question || message.includes(question)) return message;
  return `${message} ${question}`;
}

function firstFollowUpQuestion(details: Record<string, unknown> | null): string | null {
  const questions = details?.follow_up_questions;
  if (!Array.isArray(questions)) return null;
  const first = questions.find((value): value is string => typeof value === "string" && value.trim().length > 0);
  return first?.trim() ?? null;
}
