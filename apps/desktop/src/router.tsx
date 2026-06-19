import { createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import App from "./App";
import Library from "@/pages/Library";
import Reader from "@/pages/Reader";
import IllustrationTest from "@/pages/IllustrationTest";
import ModelManager from "@/pages/ModelManager";

// 建立根路由（Root Route），做為所有子頁面的外層容器
const rootRoute = createRootRoute({
  component: App,
});

// 書庫頁路由
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: Library,
});

// 閱讀頁路由
const readerRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/reader",
  component: Reader,
});

// 插圖測試頁路由
const illustrationTestRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/illustration-test",
  component: IllustrationTest,
});

// 模型管理頁路由
const modelManagerRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/models",
  component: ModelManager,
});

// 組合路由樹
const routeTree = rootRoute.addChildren([indexRoute, readerRoute, illustrationTestRoute, modelManagerRoute]);

// 建立 Router 實例
export const router = createRouter({ routeTree });

// 註冊 TanStack Router 的型別安全支援
declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
export default router;
