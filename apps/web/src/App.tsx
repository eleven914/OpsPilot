import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Card, Col, Empty, Form, Input, Layout, List, Row, Select, Space, Spin, Statistic, Tag, Timeline, Typography } from "antd";
import { AlertOutlined, ApiOutlined, SafetyCertificateOutlined } from "@ant-design/icons";
import { Approval, createIncident, decideApproval, Incident, incidentEventsUrl, listApprovals, listIncidents, TraceEvent } from "./api";

const { Header, Content } = Layout;
const { Title, Text, Paragraph } = Typography;

export default function App() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [selected, setSelected] = useState<Incident>();
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();

  useEffect(() => {
    let active = true;

    void Promise.all([listIncidents(), listApprovals()])
      .then(([data, pending]) => {
        if (!active) return;
        setIncidents(data);
        setSelected(data[0]);
        setApprovals(pending);
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(reason instanceof Error ? reason.message : "未知错误");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!selected || ["RESOLVED", "FAILED", "REJECTED", "NEEDS_HUMAN"].includes(selected.status)) return;
    const after = selected.trace.at(-1)?.sequence ?? 0;
    const source = new EventSource(incidentEventsUrl(selected.id, after));
    const eventTypes = ["task_queued", "task_started", "task_restarted", "task_failed", "state_transition", "tool_call", "proposed_action", "final_answer", "tool_result", "verification"];
    const receive = (raw: Event) => {
      const event = JSON.parse((raw as MessageEvent<string>).data) as TraceEvent;
      if (event.event_type === "state_transition" && event.payload.state === "WAITING_APPROVAL") {
        void listApprovals().then(setApprovals).catch((reason: unknown) => {
          setError(reason instanceof Error ? reason.message : "无法加载待审批动作");
        });
      }
      if (event.event_type === "state_transition" && event.payload.state === "WAITING_APPROVAL") {
        void listApprovals().then(setApprovals).catch((reason: unknown) => {
          setError(reason instanceof Error ? reason.message : "无法加载待审批动作");
        });
      }
      setSelected((current) => {
        if (!current || current.id !== selected.id || current.trace.some((item) => item.id === event.id)) return current;
        const taskState = ["task_started", "task_restarted"].includes(event.event_type) ? "RUNNING" : event.event_type === "task_failed" ? "FAILED" : undefined;
        const state = event.event_type === "state_transition" && typeof event.payload.state === "string" ? event.payload.state : taskState ?? current.status;
        const updated = { ...current, status: state, trace: [...current.trace, event] };
        setIncidents((items) => items.map((item) => item.id === updated.id ? updated : item));
        if (["RESOLVED", "FAILED", "REJECTED", "NEEDS_HUMAN"].includes(state)) {
          setApprovals((items) => items.filter((item) => item.incident_id !== updated.id));
        }
        return updated;
      });
    };
    eventTypes.forEach((eventType) => source.addEventListener(eventType, receive));
    return () => source.close();
  }, [selected]);

  const evidenceCount = useMemo(
    () => selected?.trace.filter((event) => event.event_type === "tool_call").length ?? 0,
    [selected]
  );

  const submit = async (values: Record<string, string>) => {
    setLoading(true);
    setError(undefined);
    try {
      const incident = await createIncident({ ...values, source: "manual" });
      setIncidents((current) => [incident, ...current]);
      setSelected(incident);
      setApprovals(await listApprovals());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "未知错误");
    } finally {
      setLoading(false);
    }
  };

  const review = async (approval: Approval, decision: "approve" | "reject") => {
    setLoading(true);
    setError(undefined);
    try {
      const incident = await decideApproval(approval.id, decision);
      setIncidents((current) => current.map((item) => item.id === incident.id ? incident : item));
      setSelected(incident);
      setApprovals((current) => current.filter((item) => item.id !== approval.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "未知错误");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Layout className="shell">
      <Header className="topbar">
        <Space><SafetyCertificateOutlined /><strong>OpsPilot</strong><Tag color="blue">PHASE 1</Tag></Space>
        <Text type="secondary">Evidence-first incident response</Text>
      </Header>
      <Content className="content">
        {error && <Alert closable message={error} type="error" onClose={() => setError(undefined)} />}
        <Row gutter={[16, 16]} className="stats">
          <Col xs={24} md={8}><Card><Statistic title="事件总数" value={incidents.length} prefix={<AlertOutlined />} /></Card></Col>
          <Col xs={24} md={8}><Card><Statistic title="当前证据" value={evidenceCount} prefix={<ApiOutlined />} /></Card></Col>
          <Col xs={24} md={8}><Card><Statistic title="待审批动作" value={approvals.length} suffix="项" /></Card></Col>
        </Row>
        <Row gutter={[16, 16]}>
          <Col xs={24} xl={8}>
            <Card title="创建故障事件">
              <Form layout="vertical" onFinish={submit} initialValues={{ severity: "P2", service_name: "gateway" }}>
                <Form.Item name="title" label="标题" rules={[{ required: true, min: 3 }]}><Input placeholder="Gateway 延迟告警" /></Form.Item>
                <Form.Item name="service_name" label="服务" rules={[{ required: true }]}>
                  <Select options={["gateway", "order", "payment", "inventory", "notification"].map((value) => ({ value, label: value }))} />
                </Form.Item>
                <Form.Item name="severity" label="严重级别" rules={[{ required: true }]}>
                  <Select options={["P1", "P2", "P3", "P4"].map((value) => ({ value, label: value }))} />
                </Form.Item>
                <Form.Item name="description" label="现象描述" rules={[{ required: true, min: 5 }]}>
                  <Input.TextArea rows={4} placeholder="描述告警、影响和观察到的现象" />
                </Form.Item>
                <Button block type="primary" htmlType="submit" loading={loading}>启动 Mock 诊断</Button>
              </Form>
            </Card>
            <Card title="事件列表" className="section-card">
              <List dataSource={incidents} locale={{ emptyText: "暂无事件" }} renderItem={(item) => (
                <List.Item className="incident-row" onClick={() => setSelected(item)}>
                  <List.Item.Meta title={<Space><Tag color={item.severity === "P1" ? "red" : "orange"}>{item.severity}</Tag>{item.title}</Space>} description={`${item.service_name} · ${item.status}`} />
                </List.Item>
              )} />
            </Card>
            <Card title="待审批动作" className="section-card">
              <List dataSource={approvals} locale={{ emptyText: "暂无待审批动作" }} renderItem={(approval) => (
                <List.Item className="approval-row">
                  <Space direction="vertical" size={8} className="approval-content">
                    <Space><Text strong>{approval.tool_name}</Text><Tag color={approval.risk === "high" ? "red" : "orange"}>{approval.risk}</Tag></Space>
                    <Text type="secondary">申请人：{approval.requested_by}</Text>
                    <Text>参数：{JSON.stringify(approval.arguments)}</Text>
                    <Text>回滚方案：{approval.rollback_plan}</Text>
                    <Text type="secondary">证据：{approval.evidence_ids.length} 项</Text>
                    <Space>
                      <Button type="primary" loading={loading} onClick={() => void review(approval, "approve")}>批准并执行</Button>
                      <Button danger loading={loading} onClick={() => void review(approval, "reject")}>拒绝</Button>
                    </Space>
                  </Space>
                </List.Item>
              )} />
            </Card>
          </Col>
          <Col xs={24} xl={16}>
            <Card title="诊断轨迹" extra={selected && <Tag color="green">{selected.status}</Tag>}>
              {loading && !selected ? <Spin /> : !selected ? <Empty description="创建事件后显示证据轨迹" /> : <>
                <Title level={3}>{selected.title}</Title>
                <Paragraph type="secondary">{selected.description}</Paragraph>
                <Timeline items={selected.trace.map((event) => ({
                  color: event.event_type === "final_answer" ? "green" : event.event_type === "tool_call" ? "blue" : "gray",
                  children: <div><Text strong>{event.event_type}</Text><pre>{JSON.stringify(event.payload, null, 2)}</pre></div>
                }))} />
              </>}
            </Card>
          </Col>
        </Row>
      </Content>
    </Layout>
  );
}
