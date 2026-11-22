import { createApp } from "vue"
import { createPinia } from "pinia"
import "@fontsource/ibm-plex-sans/400.css"
import "@fontsource/ibm-plex-sans/600.css"
import "@fontsource/ibm-plex-mono/400.css"
import "@fontsource/ibm-plex-mono/600.css"
import "./styles/theme.css"
import App from "./App.vue"
import { router } from "./router"

createApp(App).use(createPinia()).use(router).mount("#app")
