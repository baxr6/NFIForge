import { onBeforeUnmount, ref, watch, type Ref } from "vue"

// damped spring so needles and bars settle like real gauges instead of jumping
export function useSpring(target: Ref<number>, stiffness = 120, damping = 16) {
  const value = ref(target.value)
  let vel = 0
  let raf = 0
  let last = 0

  function step(timestamp: number) {
    // first frame or clock going backwards (tab wake, throttled timers) must not give a negative step
    const elapsed = last ? Math.min(Math.max((timestamp - last) / 1000, 0), 0.05) : 1 / 60
    last = timestamp
    if (!Number.isFinite(value.value) || !Number.isFinite(vel)) { value.value = target.value; vel = 0 }
    const force = stiffness * (target.value - value.value) - damping * vel
    vel += force * elapsed
    value.value += vel * elapsed
    if (Math.abs(target.value - value.value) < 1e-4 && Math.abs(vel) < 1e-4) {
      value.value = target.value
      raf = 0
      return
    }
    raf = requestAnimationFrame(step)
  }

  watch(target, () => {
    if (!raf) {
      last = 0
      raf = requestAnimationFrame(step)
    }
  })
  onBeforeUnmount(() => cancelAnimationFrame(raf))
  return value
}
