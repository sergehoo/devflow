import { createBrowserRouter } from "react-router";
import { AppLayout } from "@/app/layouts/AppLayout";
import { NotFound, RouteError } from "./RouteViews";

export const router = createBrowserRouter(
  [
    {
      path: "/login",
      lazy: async () => ({ Component: (await import("@/features/auth/LoginPage")).LoginPage }),
    },
    {
      path: "/",
      element: <AppLayout />,
      errorElement: <RouteError />,
      handle: { crumb: "Accueil" },
      children: [
        { index: true, lazy: async () => ({ Component: (await import("@/features/dashboard/DashboardPage")).DashboardPage }) },
        {
          path: "workspaces",
          handle: { crumb: "Workspaces" },
          children: [
            { index: true, lazy: async () => ({ Component: (await import("@/features/workspaces/WorkspacesPage")).WorkspacesPage }) },
            { path: "new", handle: { crumb: "Nouveau" }, lazy: async () => ({ Component: (await import("@/features/workspaces/WorkspaceFormPage")).WorkspaceFormPage }) },
            { path: ":id", handle: { crumb: "Fiche" }, lazy: async () => ({ Component: (await import("@/features/workspaces/WorkspaceDetailPage")).WorkspaceDetailPage }) },
            { path: ":id/edit", handle: { crumb: "Modifier" }, lazy: async () => ({ Component: (await import("@/features/workspaces/WorkspaceFormPage")).WorkspaceFormPage }) },
          ],
        },
        {
          path: "projects",
          handle: { crumb: "Projets" },
          children: [
            { index: true, lazy: async () => ({ Component: (await import("@/features/projects/ProjectsPage")).ProjectsPage }) },
            { path: "new", handle: { crumb: "Nouveau" }, lazy: async () => ({ Component: (await import("@/features/projects/ProjectFormPage")).ProjectFormPage }) },
            { path: ":id", handle: { crumb: "Fiche" }, lazy: async () => ({ Component: (await import("@/features/projects/ProjectDetailPage")).ProjectDetailPage }) },
            { path: ":id/edit", handle: { crumb: "Modifier" }, lazy: async () => ({ Component: (await import("@/features/projects/ProjectFormPage")).ProjectFormPage }) },
          ],
        },
        {
          path: "tasks",
          handle: { crumb: "Tâches" },
          children: [
            { index: true, lazy: async () => ({ Component: (await import("@/features/tasks/TasksPage")).TasksPage }) },
            { path: "new", handle: { crumb: "Nouvelle" }, lazy: async () => ({ Component: (await import("@/features/tasks/TaskFormPage")).TaskFormPage }) },
            { path: ":id", handle: { crumb: "Fiche" }, lazy: async () => ({ Component: (await import("@/features/tasks/TaskDetailPage")).TaskDetailPage }) },
            { path: ":id/edit", handle: { crumb: "Modifier" }, lazy: async () => ({ Component: (await import("@/features/tasks/TaskFormPage")).TaskFormPage }) },
          ],
        },
        {
          path: "timesheets",
          handle: { crumb: "Timesheets" },
          children: [
            { index: true, lazy: async () => ({ Component: (await import("@/features/timesheets/WeekPage")).WeekPage }) },
            { path: "month", handle: { crumb: "Mois" }, lazy: async () => ({ Component: (await import("@/features/timesheets/MonthPage")).MonthPage }) },
            { path: "history", handle: { crumb: "Historique" }, lazy: async () => ({ Component: (await import("@/features/timesheets/HistoryPage")).HistoryPage }) },
            { path: "validation", handle: { crumb: "Validation" }, lazy: async () => ({ Component: (await import("@/features/timesheets/ValidationPage")).ValidationPage }) },
          ],
        },
        {
          path: "teams",
          handle: { crumb: "Équipes" },
          children: [
            { index: true, lazy: async () => ({ Component: (await import("@/features/teams/TeamsPage")).TeamsPage }) },
            { path: "new", handle: { crumb: "Nouvelle" }, lazy: async () => ({ Component: (await import("@/features/teams/FormPages")).TeamFormPage }) },
            { path: ":id", handle: { crumb: "Fiche" }, lazy: async () => ({ Component: (await import("@/features/teams/TeamDetailPage")).TeamDetailPage }) },
            { path: ":id/edit", handle: { crumb: "Modifier" }, lazy: async () => ({ Component: (await import("@/features/teams/FormPages")).TeamFormPage }) },
          ],
        },
        {
          path: "members",
          handle: { crumb: "Membres" },
          children: [
            { index: true, lazy: async () => ({ Component: (await import("@/features/teams/MembersPage")).MembersPage }) },
            { path: "new", handle: { crumb: "Intégration" }, lazy: async () => ({ Component: (await import("@/features/teams/FormPages")).MemberFormPage }) },
            { path: ":id/edit", handle: { crumb: "Modifier" }, lazy: async () => ({ Component: (await import("@/features/teams/FormPages")).MemberFormPage }) },
          ],
        },
        { path: "branding", lazy: async () => ({ Component: (await import("@/features/workspaces/BrandingRedirect")).BrandingRedirect }) },
        { path: "my-day", handle: { crumb: "Ma journée" }, lazy: async () => ({ Component: (await import("@/features/myday/MyDayPage")).MyDayPage }) },
        {
          path: "m/:resource",
          handle: { crumb: "Module" },
          children: [
            { index: true, lazy: async () => ({ Component: (await import("@/features/resources/ResourcePages")).ResourceListPage }) },
            { path: "new", handle: { crumb: "Nouveau" }, lazy: async () => ({ Component: (await import("@/features/resources/ResourcePages")).ResourceFormPage }) },
            { path: ":id", handle: { crumb: "Fiche" }, lazy: async () => ({ Component: (await import("@/features/resources/ResourcePages")).ResourceDetailPage }) },
            { path: ":id/edit", handle: { crumb: "Modifier" }, lazy: async () => ({ Component: (await import("@/features/resources/ResourcePages")).ResourceFormPage }) },
          ],
        },
        {
          path: "messenger",
          handle: { crumb: "Messagerie" },
          lazy: async () => ({ Component: (await import("@/features/messenger/MessengerPage")).MessengerPage }),
        },
        {
          path: "notifications",
          handle: { crumb: "Notifications" },
          children: [
            { index: true, lazy: async () => ({ Component: (await import("@/features/notifications/NotificationsPage")).NotificationsPage }) },
            { path: "preferences", handle: { crumb: "Préférences" }, lazy: async () => ({ Component: (await import("@/features/notifications/PreferencesPage")).PreferencesPage }) },
          ],
        },
        { path: "*", element: <NotFound /> },
      ],
    },
  ],
  { basename: "/app" },
);
