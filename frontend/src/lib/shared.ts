import { onBeforeUnmount, onMounted } from "vue"

// a page's state is made once and shared by its panels wherever they sit (any page can show them). polling
// runs while at least one of those panels is on screen and stops when the last one goes.
export function sharedPoll(fn: () => void, ms: number) {
  let users = 0
  let timer = 0
  return () => {
    onMounted(() => {
      if (users++ === 0) { fn(); timer = window.setInterval(fn, ms) }
    })
    onBeforeUnmount(() => {
      if (--users === 0) clearInterval(timer)
    })
  }
}

export function once<T>(make: () => T): () => T {
  let value: T | undefined
  return () => (value ??= make())
}
