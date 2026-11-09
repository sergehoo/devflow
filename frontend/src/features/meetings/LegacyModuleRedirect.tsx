import { Navigate, useLocation } from "react-router";
import { meetingModuleTarget } from "./constants";

/** Anciennes pages génériques `/m/meeting…` → pages réunions dédiées (cf. `meetingModuleTarget`). */
export function LegacyModuleRedirect() {
  const { pathname, search } = useLocation();
  return <Navigate to={meetingModuleTarget(pathname, search)} replace />;
}
