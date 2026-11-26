// All at Once: loads data, starts the scroll engine, mounts chapters in story order.
import "./styles.css";
import { motionSwitch } from "./lib/a11y.js";
import { loadData } from "./lib/data.js";
import { mountOpening } from "./charts/opening.js";
import { mountLocal } from "./charts/local.js";
import { mountShocks } from "./charts/shocks.js";
import { mountAppointments, mountCompare } from "./charts/appointments.js";
import { mountIran, mountSpeed, mountRidge } from "./charts/waves.js";
import { mountWeatherMap, mountUsualDay, mountHolidays } from "./charts/rituals.js";
import { mountClocks } from "./charts/clocks.js";
import { mountYourTurn } from "./charts/yourturn.js";

motionSwitch(document.getElementById("motion-switch"));

const chapters = [
  ["opening.json", "opening-chart", mountOpening],
  ["local.json", "local-chart", mountLocal],
  ["shocks_chart.json", "shocks-chart", mountShocks],
  ["appointments_daily.json", "appt-chart", mountAppointments],
  ["appointments_compare.json", "appt-compare", mountCompare],
  ["waves_daily.json", "waves-iran", mountIran],
  ["waves_speed.json", "waves-speed", mountSpeed],
  ["waves_chart.json", "waves-ridge", mountRidge],
  ["weather_day.json", "rit-map", mountWeatherMap],
  ["weather_day.json", "rit-day", mountUsualDay],
  ["rituals.json", "rit-hol", mountHolidays],
  ["two_clocks.json", "clk-chart", mountClocks],
  ["days.json", "yourturn-root", mountYourTurn],
];

for (const [file, id, mount] of chapters) {
  loadData(file)
    .then((data) => mount(document.getElementById(id), data))
    .catch((err) => console.error(`${id}:`, err));
}

// a refresh always starts on the title screen (also when the browser restores a page from its back/forward cache)
window.addEventListener("load", () => window.scrollTo(0, 0));
window.addEventListener("pageshow", (e) => { if (e.persisted) window.scrollTo(0, 0); });
