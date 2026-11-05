/** Miroir UX de RBACService._matches (la sécurité reste appliquée par Django). */
export function can(permissions: readonly string[] | undefined, action: string): boolean {
  if (!permissions?.length) return false;
  if (permissions.includes("*") || permissions.includes(action)) return true;
  const domain = action.includes(".") ? action.split(".", 1)[0] : action;
  return permissions.includes(`${domain}.*`);
}
