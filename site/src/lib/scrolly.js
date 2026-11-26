// Scrollama engine: a step changes when its card crosses 50% of the viewport, and reverses when scrolling back.
import scrollama from "scrollama";

const instances = [];

/**
 * container: a .scrolly element with .steps > .step children.
 * onStep(index, direction, stepEl) is called on enter; steps toggle .is-active.
 */
export function scrolly(container, onStep, { offset = 0.5 } = {}) {
  const steps = [...container.querySelectorAll(".step")];
  const s = scrollama();
  s.setup({ step: steps, offset })
    .onStepEnter(({ index, direction, element }) => {
      steps.forEach((el, k) => el.classList.toggle("is-active", k === index));
      onStep(index, direction, element);
    });
  instances.push(s);
  return s;
}

/** Fire once when an element first reaches 50% of the viewport (for "enters view" triggers). */
export function onEnterView(el, fn, { offset = 0.5, once = true } = {}) {
  const s = scrollama();
  let done = false;
  s.setup({ step: [el], offset }).onStepEnter(({ direction }) => {
    if (once && done) return;
    done = true;
    fn(direction);
  });
  instances.push(s);
  return s;
}

let t;
window.addEventListener("resize", () => {
  clearTimeout(t);
  t = setTimeout(() => instances.forEach((s) => s.resize()), 150);
});
