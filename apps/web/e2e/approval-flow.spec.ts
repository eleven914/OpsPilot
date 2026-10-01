import { expect, test } from "@playwright/test";

test("operator diagnoses an incident and approver executes the safe action", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("OpsPilot")).toBeVisible();

  await page.getByLabel("标题").fill("Gateway CPU saturation E2E");
  await page.getByLabel("现象描述").fill("gateway cpu and latency are increasing");
  await page.getByRole("button", { name: "启动 Mock 诊断" }).click();

  await expect(page.getByText("WAITING_APPROVAL").first()).toBeVisible();
  await expect(page.getByText("restart_service", { exact: true })).toBeVisible();
  await expect(page.getByText("medium", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "批准并执行" }).click();
  await expect(page.getByText("RESOLVED").first()).toBeVisible();
  await expect(page.getByText("tool_result", { exact: true })).toBeVisible();
  await expect(page.getByText("verification", { exact: true })).toBeVisible();
});

test("approver can reject a high-risk rollback", async ({ page }) => {
  await page.request.post("http://127.0.0.1:8010/api/v1/incidents", {
    headers: { "X-User-Id": "demo-operator", "X-Role": "operator" },
    data: {
      title: "Order release regression E2E",
      description: "order release regression after deploy",
      severity: "P1",
      service_name: "order"
    }
  });
  await page.goto("/");
  await expect(page.getByText("rollback_deployment", { exact: true })).toBeVisible();
  await expect(page.getByText("high", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /拒/ }).click();
  await expect(page.getByText("REJECTED").first()).toBeVisible();
});

test("expired approval becomes needs-human without executing", async ({ page }) => {
  await page.request.post("http://127.0.0.1:8010/api/v1/incidents", {
    headers: { "X-User-Id": "demo-operator", "X-Role": "operator" },
    data: {
      title: "Notification memory leak E2E",
      description: "notification memory leak near OOM",
      severity: "P2",
      service_name: "notification"
    }
  });
  await page.goto("/");
  await expect(page.getByText("WAITING_APPROVAL").first()).toBeVisible();

  await page.waitForTimeout(5_500);
  await page.request.get("http://127.0.0.1:8010/api/v1/approvals", {
    headers: { "X-User-Id": "e2e-approver", "X-Role": "approver" }
  });
  await expect(page.getByText("NEEDS_HUMAN").first()).toBeVisible();
  await expect(page.getByText("暂无待审批动作")).toBeVisible();
});
