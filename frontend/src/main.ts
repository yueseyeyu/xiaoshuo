/**
 * 应用入口 — 注册 Vue + Pinia + Router
 */
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'

const app = createApp(App)

// 全局错误处理 — 捕获组件内未处理的异常
app.config.errorHandler = (err, _instance, info) => {
  console.error('[Vue Error]', info, err)
}

app.use(createPinia())
app.use(router)
app.mount('#app')
