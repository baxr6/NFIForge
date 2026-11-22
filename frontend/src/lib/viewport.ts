import { ref } from "vue"

// desktop layout (panel grid, sidebar) from 1024 px (tailwind lg); below that the phone layout: panels stacked, the
// page does the scrolling
const query = window.matchMedia("(min-width: 1024px)")
export const wide = ref(query.matches)
query.addEventListener("change", () => (wide.value = query.matches))
