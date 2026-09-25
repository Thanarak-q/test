// Display formatting only. Dates are shown in Asia/Bangkok, the zone the API
// reports usage days in.
export const formatDate = (date: string) =>
  new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "Asia/Bangkok",
  }).format(new Date(date));

export const formatNumber = (value: number) => new Intl.NumberFormat("en-US").format(value);
