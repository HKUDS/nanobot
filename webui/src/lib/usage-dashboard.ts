import type { UsageDetails } from "@/lib/types";

/** ISO calendar dates supplied by the gateway, not browser-local 24-hour arithmetic. */
export function usageCalendar(details: UsageDetails) {
  const byDate = new Map(details.days.map(day => [day.date, day]));
  const cursor = new Date(`${details.start_date}T00:00:00Z`);
  const result: { date: string; usage?: UsageDetails["days"][number] }[] = [];
  while (result.length < 400 && Number.isFinite(cursor.getTime())) {
    const date = cursor.toISOString().slice(0, 10);
    if (date > details.end_date) break;
    result.push({ date, usage: byDate.get(date) });
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return result;
}

export function usageModelLabel(provider: string, model: string) {
  return model.startsWith(`${provider}/`) ? model : `${provider}/${model}`;
}
