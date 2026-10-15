import type { ChartDef } from "../workbench";

/** Inferred-chart gallery over the lettings views. Each entry is only a title and a SQL query: the back-end describes
 *  the result and infers the chart, so these cover six different result shapes with no per-chart rendering code.
 *  (The one override forces a donut, because a share table is indistinguishable from a bar-chart table.) */
export const GALLERY: ChartDef[] = [
  {
    id: "combo",
    title: "New listings and rent per week",
    subtitle: "Result: 1 date + 3 measures of different units → combo chart with a second axis",
    height: 300,
    sql: `WITH w AS (
  SELECT date_trunc('week', current_date - days_on_market)::date AS week_start,
         count(*) AS homes, avg(rent_pcm) AS avg_rent
  FROM v_properties GROUP BY 1
)
SELECT to_char(week_start, 'YYYY-MM-DD') AS week, homes,
       round(avg(homes) OVER (ORDER BY week_start ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 1) AS moving_avg,
       round(avg_rent) AS avg_rent_pcm
FROM w ORDER BY week_start`,
  },
  {
    id: "stacked",
    title: "Homes by size in each postcode area",
    subtitle: "Result: 1 category + 3 similar measures → stacked bars",
    sql: `SELECT outcode,
       count(*) FILTER (WHERE bedrooms <= 1) AS one_bed_or_less,
       count(*) FILTER (WHERE bedrooms = 2)  AS two_bed,
       count(*) FILTER (WHERE bedrooms >= 3) AS three_plus_bed
FROM v_properties WHERE outcode IS NOT NULL
GROUP BY outcode ORDER BY outcode`,
  },
  {
    id: "multi",
    title: "New listings per week by bedrooms",
    subtitle: "Result: long-form (date, category, value) → pivoted into one line per category",
    sql: `SELECT to_char(date_trunc('week', current_date - days_on_market), 'YYYY-MM-DD') AS week,
       CASE WHEN bedrooms >= 3 THEN '3+' ELSE bedrooms::text END AS beds,
       count(*) AS homes
FROM v_properties WHERE bedrooms IS NOT NULL
GROUP BY 1, 2 ORDER BY 1, 2`,
  },
  {
    id: "donut",
    title: "Homes by property type",
    subtitle: "Result: category + value + share → donut (type forced), share column shown in tooltip",
    height: 260,
    override: { type: "pie" },
    sql: `SELECT property_type, count(*) AS homes,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct
FROM v_properties WHERE property_type IS NOT NULL
GROUP BY property_type ORDER BY homes DESC LIMIT 6`,
  },
  {
    id: "bubble",
    title: "Commute against rent",
    subtitle: "Result: a text label + measures → bubble scatter labelled by address (needs your work address)",
    sql: `SELECT address, work_am_min, rent_pcm, days_on_market
FROM v_properties WHERE work_am_min IS NOT NULL
ORDER BY rent_pcm LIMIT 300`,
  },
  {
    id: "borough",
    title: "Average rent by borough",
    subtitle: "Result: 1 category + 1 measure → bar",
    height: 240,
    sql: `SELECT borough, round(avg(rent_pcm)) AS avg_rent_pcm
FROM v_properties WHERE borough IS NOT NULL
GROUP BY borough ORDER BY avg_rent_pcm DESC`,
  },
];
