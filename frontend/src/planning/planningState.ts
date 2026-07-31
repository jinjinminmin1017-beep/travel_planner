import type { AsyncJobStatus, PlanningStatus, TravelPlanResponse } from "../types";

const ACTIVE_PLANNING_STATUSES = new Set<PlanningStatus>(["PENDING", "RUNNING"]);
const ACTIVE_JOB_STATUSES = new Set<AsyncJobStatus>(["QUEUED", "RUNNING", "WAITING_SOURCE"]);

export type PlanningObservationState = "IDLE" | "SUBMITTING" | "OBSERVING" | "PAUSED";
export type PlanningErrorType = "NONE" | "BLOCKING" | "NON_BLOCKING";
export type PlanningPageState =
  | "IDLE"
  | "BLOCKING_ERROR"
  | "SUBMITTING"
  | "PLANNING_EMPTY"
  | "PLANNING_WITH_RESULTS"
  | "OBSERVATION_PAUSED"
  | "NO_MATCH"
  | "FAILED"
  | "RESULTS"
  | "EMPTY";

type PlanningStatusSnapshot = Pick<TravelPlanResponse, "planning_status" | "plans"> & {
  async_job?: Pick<NonNullable<TravelPlanResponse["async_job"]>, "job_status"> | null;
};

export interface PlanningPageStateInput {
  response: PlanningStatusSnapshot | null;
  observationState: PlanningObservationState;
  errorType: PlanningErrorType;
}

export interface PollTimingOptions {
  baseDelayMs: number;
  maxDelayMs: number;
  backoffFactor: number;
  jitterRatio: number;
}

export const DEFAULT_OBSERVATION_WINDOW_MS = 120_000;
export const DEFAULT_POLL_TIMING: PollTimingOptions = {
  baseDelayMs: 1_200,
  maxDelayMs: 5_000,
  backoffFactor: 1.25,
  jitterRatio: 0.15
};

export function isPlanningActive(response: PlanningStatusSnapshot): boolean {
  return ACTIVE_PLANNING_STATUSES.has(response.planning_status)
    || Boolean(response.async_job && ACTIVE_JOB_STATUSES.has(response.async_job.job_status));
}

export function isPlanningTerminal(response: PlanningStatusSnapshot): boolean {
  return !isPlanningActive(response);
}

export function derivePlanningPageState(input: PlanningPageStateInput): PlanningPageState {
  const { response, observationState, errorType } = input;
  if (!response) {
    if (errorType === "BLOCKING") return "BLOCKING_ERROR";
    if (observationState === "SUBMITTING") return "SUBMITTING";
    return "IDLE";
  }

  if (isPlanningActive(response)) {
    if (observationState === "PAUSED") return "OBSERVATION_PAUSED";
    return response.plans.length > 0 ? "PLANNING_WITH_RESULTS" : "PLANNING_EMPTY";
  }

  if (response.planning_status === "NO_MATCH") return "NO_MATCH";
  if (
    response.planning_status === "FAILED"
    || response.async_job?.job_status === "FAILED"
    || response.async_job?.job_status === "CANCELLED"
  ) {
    return "FAILED";
  }
  return response.plans.length > 0 ? "RESULTS" : "EMPTY";
}

export function hasObservationWindowExpired(startedAtMs: number, nowMs: number, windowMs: number): boolean {
  return nowMs - startedAtMs >= Math.max(0, windowMs);
}

export function nextPollDelayMs(
  attempt: number,
  randomValue = Math.random(),
  options: PollTimingOptions = DEFAULT_POLL_TIMING
): number {
  const backoffDelay = Math.min(
    options.maxDelayMs,
    options.baseDelayMs * (options.backoffFactor ** Math.max(0, attempt))
  );
  const normalizedRandom = Math.min(1, Math.max(0, randomValue));
  const jitterMultiplier = 1 + ((normalizedRandom * 2) - 1) * options.jitterRatio;
  return Math.max(0, Math.round(backoffDelay * jitterMultiplier));
}
