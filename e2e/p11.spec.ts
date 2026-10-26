import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

/**
 * P11 browser E2E: eight scenarios against the real server (e2e/fixture_server.py). Serial, because the approve/reject
 * scenario changes the data the following scenarios read. Seeded data (tenant "acme"):
 *   INC-1001, INC-1002  HITL pending, grounded investigation
 *   INC-1003            degraded investigation (nothing stored, nothing to approve)
 *   INC-1004            HITL pending, investigation text carries hostile markup
 * Tenant "globex" has one workflow of its own that must never appear for an acme user.
 */
test.describe.configure({ mode: "serial" });

const tokens: Record<string, string> = JSON.parse(
  fs.readFileSync(path.join(__dirname, ".runtime", "tokens.json"), "utf-8"),
);

async function trackCspViolations(page: Page) {
  await page.addInitScript(() => {
    (window as unknown as { __csp: string[] }).__csp = [];
    document.addEventListener("securitypolicyviolation", (event) =>
      (window as unknown as { __csp: string[] }).__csp.push(event.violatedDirective),
    );
  });
  const consoleViolations: string[] = [];
  page.on("console", (message) => {
    if (/content security policy/i.test(message.text())) consoleViolations.push(message.text());
  });
  return consoleViolations;
}

async function expectNoCspViolations(page: Page, consoleViolations: string[]) {
  const reported = await page.evaluate(() => (window as unknown as { __csp?: string[] }).__csp ?? []);
  expect(reported, "securitypolicyviolation events").toEqual([]);
  expect(consoleViolations, "CSP console errors").toEqual([]);
}

async function expectTokenNotStored(page: Page, token: string) {
  const stored = await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage }, cookie: document.cookie }));
  expect(stored).not.toContain(token);
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
  const cookies = await page.context().cookies();
  expect(JSON.stringify(cookies)).not.toContain(token);
  expect(cookies).toEqual([]);
}

async function signIn(page: Page, user: string) {
  await page.goto("/ui/");
  await page.getByLabel("Bearer token").fill(tokens[user]);
  await page.getByRole("button", { name: "Connect" }).click();
  await expect(page.getByTestId("who")).toContainText(user === "omar" ? "Omar Operator" : "Rita Reviewer");
}

const auth = (user: string) => ({ Authorization: `Bearer ${tokens[user]}` });

test("1. the user enters an authentication token (kept in memory only)", async ({ page }) => {
  const csp = await trackCspViolations(page);
  await page.goto("/ui/");
  await expect(page.getByRole("heading", { name: "Connect to PulseOps" })).toBeVisible();
  expect(await page.getByLabel("Bearer token").getAttribute("type")).toBe("password");

  await page.getByLabel("Bearer token").fill("not-a-valid-token-0123456789abcdef");
  await page.getByRole("button", { name: "Connect" }).click();
  const alert = page.getByRole("alert");
  await expect(alert).toContainText("Authentication required");
  await expect(alert).toContainText("unauthorized");
  await expect(page.getByTestId("who")).toHaveCount(0);

  await page.getByLabel("Bearer token").fill(tokens["rita"]);
  await page.getByRole("button", { name: "Connect" }).click();
  await expect(page.getByTestId("who")).toContainText("Acme Corp");
  await expect(page.getByTestId("who")).toContainText("reviewer");
  await expectTokenNotStored(page, tokens["rita"]);
  await expect(page.locator("body")).not.toContainText(tokens["rita"]);
  expect(page.url()).not.toContain(tokens["rita"]);

  await page.reload(); // a reload forgets the token by design
  await expect(page.getByRole("heading", { name: "Connect to PulseOps" })).toBeVisible();
  await expectNoCspViolations(page, csp);
});

test("2. the incident list loads and shows only the user's tenant", async ({ page }) => {
  const csp = await trackCspViolations(page);
  await signIn(page, "rita");
  await expect(page.getByRole("heading", { name: "Incidents" })).toBeVisible();
  for (const id of ["INC-1001", "INC-1002", "INC-1003", "INC-1004"]) {
    await expect(page.getByRole("link", { name: id })).toBeVisible();
  }
  await expect(page.getByTestId("page-range")).toHaveText("1–4 of 4"); // globex's incident is not in acme's list
  await expect(page.locator("tbody tr")).toHaveCount(4);
  await page.getByLabel(/^Severity/).selectOption("low");
  await expect(page.getByText("No incidents match.")).toBeVisible();
  await expectNoCspViolations(page, csp);
});

test("3. an incident opens in the detail view", async ({ page }) => {
  const csp = await trackCspViolations(page);
  await signIn(page, "rita");
  await page.getByRole("link", { name: "INC-1001" }).click();
  await expect(page).toHaveURL(/#\/incidents\/INC-1001$/);
  await expect(page.getByRole("heading", { name: /INC-1001:/ })).toBeVisible();
  await expect(page.getByText("Checkout latency above threshold")).toBeVisible();
  await expect(page.getByTestId("workflow-status")).toHaveText("pending");
  await expect(page.getByTestId("hitl-state")).toContainText("Awaiting a human decision");
  await expect(page.getByText("INCIDENT_RECEIVED")).toBeVisible(); // audit timeline
  await expectNoCspViolations(page, csp);
});

test("4. the investigation is labelled AI-generated with evidence, hypotheses, gaps and recommendations kept apart", async ({ page }) => {
  const csp = await trackCspViolations(page);
  await signIn(page, "rita");
  await page.goto("/ui/#/incidents/INC-1001");
  await expect(page.getByText("AI-generated").first()).toBeVisible();
  const evidence = page.getByRole("region", { name: "Evidence" });
  const hypotheses = page.getByRole("region", { name: "Hypotheses (unconfirmed)" });
  const missing = page.getByRole("region", { name: "Missing information" });
  const recommendations = page.getByRole("region", { name: "Recommendations (suggestions, not actions taken)" });
  await expect(evidence).toContainText("Scripted evidence: error rate rose at 10:02");
  await expect(hypotheses).toContainText("Hypothesis: Scripted hypothesis: the connection pool may be undersized");
  await expect(missing).toContainText("Scripted gap: no database metrics were available");
  await expect(recommendations).toContainText("Recommendation: Scripted recommendation: consider restarting the service");
  await expect(recommendations).toContainText("None of these has been performed");
  await expect(evidence).not.toContainText("Scripted hypothesis");
  await expect(evidence).not.toContainText("consider restarting");
  await expect(page.getByText(/Confidence \(AI-estimated\): 72%/)).toBeVisible();
  await expectNoCspViolations(page, csp);
});

test("5. the pending approval queue loads", async ({ page }) => {
  const csp = await trackCspViolations(page);
  await signIn(page, "rita");
  await page.getByRole("link", { name: "Pending approvals" }).click();
  await expect(page.getByRole("heading", { name: "Pending approvals" })).toBeVisible();
  const items = page.getByTestId("approval-item");
  await expect(items).toHaveCount(3); // INC-1001, INC-1002, INC-1004: not the degraded INC-1003, not globex's workflow
  await expect(items.filter({ hasText: "INC-1003" })).toHaveCount(0);
  await expect(items.first()).toContainText("restart_service");
  await expect(items.first()).toContainText("awaiting decision");
  await expect(items.first()).toContainText("AI-generated");
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(3); // the reviewer may decide all three
  await expectNoCspViolations(page, csp);
});

test("6. an authorised reviewer approves one workflow and rejects another", async ({ page }) => {
  const csp = await trackCspViolations(page);
  await signIn(page, "rita");
  await page.goto("/ui/#/approvals");
  const first = page.getByTestId("approval-item").filter({ hasText: "INC-1001" });
  await first.getByLabel("Rationale (optional)").fill("e2e approve");
  await first.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByTestId("approval-item").filter({ hasText: "INC-1001" })).toHaveCount(0);

  const second = page.getByTestId("approval-item").filter({ hasText: "INC-1002" });
  await second.getByRole("button", { name: "Reject" }).click();
  await expect(page.getByTestId("approval-item").filter({ hasText: "INC-1002" })).toHaveCount(0);
  await expect(page.getByTestId("approval-item")).toHaveCount(1); // INC-1004 is still pending

  await page.goto("/ui/#/incidents/INC-1001");
  await expect(page.getByTestId("hitl-state")).toContainText("Approved by a human reviewer");
  await expect(page.getByTestId("hitl-state")).toContainText("did not execute");
  await expect(page.getByTestId("workflow-status")).toHaveText("approved");
  await page.goto("/ui/#/incidents/INC-1002");
  await expect(page.getByTestId("hitl-state")).toContainText("Rejected by a human reviewer");
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
  await expectNoCspViolations(page, csp);
});

test("7. an operator has no reviewer controls and a forced approval is refused with 403", async ({ page }) => {
  const csp = await trackCspViolations(page);
  await signIn(page, "omar");
  await page.goto("/ui/#/approvals");
  const item = page.getByTestId("approval-item").filter({ hasText: "INC-1004" });
  await expect(item).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Reject" })).toHaveCount(0);
  await expect(item.getByTestId("cannot-decide")).toContainText("You cannot decide this workflow");

  // the button is absent, but the backend is what refuses: forge the request the button would have sent
  const detail = await page.request.get("/incidents/INC-1004/detail", { headers: auth("omar") });
  const workflowId = (await detail.json()).workflow.workflow_id as string;
  const body = { decision: "approve", incident_id: "INC-1004", action: "restart_service", timestamp: new Date().toISOString() };
  const forgedOperator = await page.request.post(`/workflow/${workflowId}/decision`, { headers: auth("omar"), data: body });
  expect(forgedOperator.status()).toBe(403);
  expect(await forgedOperator.json()).toMatchObject({ code: "forbidden" });
  const forgedService = await page.request.post(`/workflow/${workflowId}/decision`, { headers: auth("svc-n8n"), data: body });
  expect(forgedService.status()).toBe(403);
  const otherTenant = await page.request.post(`/workflow/${workflowId}/decision`, { headers: auth("gina"), data: body });
  expect([403, 404]).toContain(otherTenant.status());
  const still = await page.request.get(`/workflow/${workflowId}`, { headers: auth("omar") });
  expect((await still.json()).status).toBe("pending"); // none of it changed anything
  await expectTokenNotStored(page, tokens["omar"]);
  await expectNoCspViolations(page, csp);
});

test("8. a degraded investigation and an API failure are visibly handled", async ({ page }) => {
  const csp = await trackCspViolations(page);
  await signIn(page, "rita");

  await page.goto("/ui/#/incidents/INC-1003"); // degraded: no grounded result exists, so none is shown
  await expect(page.getByTestId("investigation-unavailable")).toContainText("could not be grounded");
  await expect(page.getByRole("region", { name: "Evidence" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
  await expect(page.getByText("AI-generated")).toHaveCount(0);

  await page.goto("/ui/#/incidents/INC-1004"); // hostile text is shown as text and never executed
  await expect(page.getByRole("region", { name: "Evidence" })).toContainText("<img src=x onerror=");
  expect(await page.locator("main img").count()).toBe(0);
  expect(await page.evaluate(() => (window as unknown as { __pwned?: number }).__pwned)).toBeUndefined();

  await page.route("**/incidents/INC-1001/detail", (route) =>
    route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "Internal server error", code: "internal_error", request_id: "req-e2e-0001" }) }),
  );
  await page.goto("/ui/#/incidents/INC-1001");
  const alert = page.getByRole("alert");
  await expect(alert).toContainText("Internal server error");
  await expect(alert).toContainText("internal_error");
  await expect(alert).toContainText("req-e2e-0001");
  await expect(page.getByRole("region", { name: "Evidence" })).toHaveCount(0); // nothing invented while the API is down
  await expectNoCspViolations(page, csp);
});
