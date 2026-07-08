/** Normalized API error for UI / logging */
export type ApiErrorBody = {
  message: string;
  status?: number;
  code?: string;
  details?: unknown;
};

export class ApiError extends Error {
  readonly status?: number;
  readonly code?: string;
  readonly details?: unknown;

  constructor(body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = body.status;
    this.code = body.code;
    this.details = body.details;
  }
}

export type CreateApiClientOptions = {
  /** Return bearer token or null (e.g. from localStorage) */
  getAccessToken?: () => string | null;
  /** Called when HTTP 401 is received */
  onUnauthorized?: () => void;
};
