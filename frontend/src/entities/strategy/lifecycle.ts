export interface StrategyTransitionCandidate {
  target_status: string;
  label: string;
}

const transitions: Record<string, StrategyTransitionCandidate[]> = {
  draft: [{ target_status: "research", label: "进入研究" }, { target_status: "paused", label: "暂停" }, { target_status: "retired", label: "归档" }],
  research: [{ target_status: "paper", label: "进入模拟盘" }, { target_status: "paused", label: "暂停" }, { target_status: "retired", label: "归档" }],
  paper: [{ target_status: "shadow_live", label: "进入影子实盘" }, { target_status: "paused", label: "暂停" }, { target_status: "retired", label: "归档" }],
  shadow_live: [{ target_status: "live", label: "进入实盘准备" }, { target_status: "paused", label: "暂停" }, { target_status: "retired", label: "归档" }],
  live: [{ target_status: "paused", label: "暂停" }, { target_status: "retired", label: "归档" }],
  paused: [{ target_status: "paper", label: "恢复模拟盘" }, { target_status: "retired", label: "归档" }],
  retired: []
};

export function transitionCandidates(status: string): StrategyTransitionCandidate[] {
  return transitions[status] ?? [];
}

export function lifecycleTone(status: string): "success" | "warning" | "danger" | "neutral" {
  if (status === "paper" || status === "shadow_live" || status === "live") {
    return "success";
  }
  if (status === "paused") {
    return "warning";
  }
  if (status === "retired") {
    return "danger";
  }
  return "neutral";
}
