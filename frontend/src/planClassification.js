export const PLAN_PRIORITIES = [
  { value: "normal", label: "Normal" },
  { value: "medium", label: "Média" },
  { value: "high", label: "Alta" },
];

export function priorityLabel(priority) {
  return PLAN_PRIORITIES.find((entry) => entry.value === priority)?.label?.toUpperCase() || "NORMAL";
}
