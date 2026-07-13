<script setup lang="ts">
/**
 * App — 根组件
 * 使用 AppLayout 包裹所有路由视图
 */
import AppLayout from '@/components/layout/AppLayout.vue'
import ConfirmModal from '@/components/common/ConfirmModal.vue'
</script>

<template>
  <AppLayout />
  <ConfirmModal />
</template>
