export type TraceEvent = {
  id: string;
  sequence: number;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type Incident = {
  id: string;
  title: string;
  description: string;
  severity: string;
  service_name: string;
  source: string;
  status: string;
  created_at: string;
  updated_at: string;
  trace: TraceEvent[];
};

export type Approval = {
  id: string;
  incident_id: string;
  requested_by: string;
  decision: string;
  expires_at: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  risk: "medium" | "high";
  evidence_ids: string[];
  rollback_plan: string;
};

const operatorHeaders = { "X-User-Id": "demo-operator", "X-Role": "operator" };
const approverHeaders = { "X-User-Id": "demo-approver", "X-Role": "approver" };

export async function listIncidents(): Promise<Incident[]> {
  const response = await fetch("/api/v1/incidents", { headers: operatorHeaders });
  if (!response.ok) throw new Error("无法加载事件");
  return response.json();
}

export async function createIncident(payload: Record<string, string>): Promise<Incident> {
  const response = await fetch("/api/v1/incidents", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...operatorHeaders },
    body: JSON.stringify(payload)
  });
  if (!response.ok) throw new Error("创建事件失败");
  return response.json();
}

export async function listApprovals(): Promise<Approval[]> {
  const response = await fetch("/api/v1/approvals", { headers: approverHeaders });
  if (!response.ok) throw new Error("无法加载待审批动作");
  return response.json();
}

export async function decideApproval(
  approvalId: string,
  decision: "approve" | "reject"
): Promise<Incident> {
  const response = await fetch(`/api/v1/approvals/${approvalId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...approverHeaders },
    body: JSON.stringify({ decision })
  });
  if (!response.ok) throw new Error(decision === "approve" ? "审批执行失败" : "拒绝操作失败");
  return response.json();
}

export function incidentEventsUrl(incidentId: string, after: number): string {
  return `/api/v1/incidents/${incidentId}/events?after=${after}`;
}
