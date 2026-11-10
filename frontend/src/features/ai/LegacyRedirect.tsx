import { Navigate, useLocation } from "react-router";
import { aiModuleTarget } from "./legacyRoutes";

/** Redirige les anciennes URL génériques (`/m/ai-proposal…`, `/m/project-import…`) vers les écrans dédiés. */
export function AIModuleRedirect() {
  const { pathname, search } = useLocation();
  return <Navigate replace to={aiModuleTarget(pathname, search)} />;
}
