/** Токен доступа хранится в localStorage; при недоступном хранилище — только в памяти. */
let memoryToken: string | null = null;

export function getToken(): string | null {
  try {
    return localStorage.getItem("token") ?? memoryToken;
  } catch {
    return memoryToken;
  }
}

export function setToken(token: string | null): void {
  memoryToken = token;
  try {
    if (token) localStorage.setItem("token", token);
    else localStorage.removeItem("token");
  } catch {
    /* хранилище недоступно */
  }
}

export class UnauthorizedError extends Error {}
