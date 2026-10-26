import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import { setToken, setUnauthorizedHandler } from "../api";

beforeEach(() => {
  window.location.hash = "";
});

afterEach(() => {
  cleanup();
  setToken(null);
  setUnauthorizedHandler(null);
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
