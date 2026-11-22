import { reactive } from "vue"

// optional parts the backend runs only when config.yaml turns them on (it says which in /api/health)
export const features = reactive({ btcgate: false, orderflow: false })
fetch("/api/health").then((response) => response.json()).then((health) => { features.btcgate = !!health.btcgate; features.orderflow = !!health.orderflow }).catch(() => {})
