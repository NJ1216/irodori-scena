import { lazy, Suspense, useSyncExternalStore } from "react";
import { isStyleGuideLocation, subscribeToStyleGuideRoute } from "./features/styleguide/styleGuideNavigation";
import { QuickTooltip } from "./features/shared/QuickTooltip";
import { DestructiveConfirmationNotice } from "./features/shared/DestructiveConfirmationNotice";

const StudioApp = lazy(() => import("./features/studio/StudioApp").then((module) => ({ default: module.StudioApp })));
const StyleGuideView = import.meta.env.DEV ? lazy(() => import("./features/styleguide/StyleGuideView").then((module) => ({ default: module.StyleGuideView }))) : null;

export default function App() {
  const styleGuideRequested = useSyncExternalStore(subscribeToStyleGuideRoute, isStyleGuideLocation);
  const view = StyleGuideView && styleGuideRequested ? <StyleGuideView /> : <StudioApp />;
  return (
    <Suspense
      fallback={
        <main className="boot">
          <div className="boot-card">🌸 読み込んでいます…</div>
        </main>
      }
    >
      {view}
      <DestructiveConfirmationNotice />
      <QuickTooltip />
    </Suspense>
  );
}
