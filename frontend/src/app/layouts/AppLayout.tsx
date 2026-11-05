import { lazy, Suspense } from "react";
import { Navigate, Outlet, useLocation } from "react-router";
import { ErrorState, PageSkeleton } from "@/components/feedback/states";
import { useMe } from "@/features/auth/api";
import { RealtimeBridge } from "@/features/realtime/RealtimeBridge";
import { Header } from "./Header";
import { MobileSidebar, Sidebar } from "./Sidebar";

// Bulle Messenger chargée après la coque : hors du chunk principal.
const MessengerBubble = lazy(async () => ({ default: (await import("@/features/messenger/MessengerBubble")).MessengerBubble }));

/** Garde d'authentification + coque applicative. */
export function AppLayout() {
  const { data: me, isLoading, isError, error, refetch } = useMe();
  const location = useLocation();

  if (isLoading) {
    return <div className="mx-auto max-w-6xl p-6"><PageSkeleton /></div>;
  }
  if (isError) {
    return <div className="mx-auto max-w-lg p-6"><ErrorState message={error.message} onRetry={() => void refetch()} /></div>;
  }
  if (!me) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-2 focus:rounded-lg focus:bg-card focus:p-2">
        Aller au contenu
      </a>
      <Sidebar me={me} />
      <MobileSidebar me={me} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header me={me} />
        <main id="main" className="mx-auto w-full max-w-7xl flex-1 p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
      <RealtimeBridge />
      <Suspense fallback={null}><MessengerBubble /></Suspense>
    </div>
  );
}
