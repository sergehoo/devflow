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
        { path: "profile", handle: { crumb: "Mon profil" }, lazy: async () => ({ Component: (await import("@/features/profile/ProfilePage")).ProfilePage }) },
        { path: "sprints/:id/board", handle: { crumb: "Board du sprint" }, lazy: async () => ({ Component: (await import("@/features/agile/SprintBoardPage")).SprintBoardPage }) },
        { path: "assistant", handle: { crumb: "Assistant IA" }, lazy: async () => ({ Component: (await import("@/features/assistant/AssistantPage")).AssistantPage }) },
        // --- finance --- cockpit financier, allocation IA, éditeur de facture
        { path: "finance/portfolio", handle: { crumb: "Cockpit financier" }, lazy: async () => ({ Component: (await import("@/features/finance/FinancePages")).FinancePortfolioPage }) },
        { path: "finance/allocation", handle: { crumb: "Allocation IA" }, lazy: async () => ({ Component: (await import("@/features/finance/FinancePages")).AllocationPage }) },
        { path: "invoices/:id", handle: { crumb: "Facture" }, lazy: async () => ({ Component: (await import("@/features/finance/FinancePages")).InvoiceEditorPage }) },
        // --- tickets --- (centre de support multi-applications)
        {
          path: "tickets",
          handle: { crumb: "Support" },
          children: [
            { index: true, lazy: async () => ({ Component: (await import("@/features/tickets/TicketsPages")).TicketCenterPage }) },
            { path: "list", handle: { crumb: "Tickets" }, lazy: async () => ({ Component: (await import("@/features/tickets/TicketsPages")).TicketsPage }) },
            { path: "applications", handle: { crumb: "Applications" }, lazy: async () => ({ Component: (await import("@/features/tickets/SupportAdminPages")).ApplicationsPage }) },
            { path: "settings", handle: { crumb: "Routage & SLA" }, lazy: async () => ({ Component: (await import("@/features/tickets/SupportAdminPages")).SupportSettingsPage }) },
            { path: "email", handle: { crumb: "Canaux e-mail" }, lazy: async () => ({ Component: (await import("@/features/tickets/EmailChannelsPage")).EmailChannelsPage }) },
            { path: ":id", handle: { crumb: "Ticket" }, lazy: async () => ({ Component: (await import("@/features/tickets/TicketDetailPage")).TicketDetailPage }) },
          ],
        },
        // --- meetings --- (réunions, séries, décisions, enregistrements ; anciennes pages génériques /m/meeting… redirigées)
        {
          path: "meetings",
          handle: { crumb: "Réunions" },
          children: [
            { index: true, lazy: async () => ({ Component: (await import("@/features/meetings/MeetingsPage")).MeetingsPage }) },
            { path: "new", handle: { crumb: "Nouvelle" }, lazy: async () => ({ Component: (await import("@/features/meetings/FormPages")).MeetingFormPage }) },
            { path: "dashboard", handle: { crumb: "Vue d'ensemble" }, lazy: async () => ({ Component: (await import("@/features/meetings/DashboardPage")).MeetingDashboardPage }) },
            { path: "decisions", handle: { crumb: "Décisions" }, lazy: async () => ({ Component: (await import("@/features/meetings/DecisionsPage")).DecisionsPage }) },
            {
              path: "series",
              handle: { crumb: "Séries" },
              children: [
                { index: true, lazy: async () => ({ Component: (await import("@/features/meetings/SeriesPages")).SeriesListPage }) },
                { path: "new", handle: { crumb: "Nouvelle" }, lazy: async () => ({ Component: (await import("@/features/meetings/FormPages")).SeriesFormPage }) },
                { path: ":id", handle: { crumb: "Fiche" }, lazy: async () => ({ Component: (await import("@/features/meetings/SeriesPages")).SeriesDetailPage }) },
                { path: ":id/edit", handle: { crumb: "Modifier" }, lazy: async () => ({ Component: (await import("@/features/meetings/FormPages")).SeriesFormPage }) },
              ],
            },
            { path: ":id", handle: { crumb: "Fiche" }, lazy: async () => ({ Component: (await import("@/features/meetings/MeetingDetailPage")).MeetingDetailPage }) },
            { path: ":id/edit", handle: { crumb: "Modifier" }, lazy: async () => ({ Component: (await import("@/features/meetings/FormPages")).MeetingFormPage }) },
            { path: ":id/recordings/:recordingId", handle: { crumb: "Enregistrement" }, lazy: async () => ({ Component: (await import("@/features/meetings/RecordingPage")).RecordingPage }) },
          ],
        },
        ...["m/meeting", "m/meeting-series", "m/meeting-decision"].map((path) => ({
          path,
          children: ["", "new", ":id", ":id/edit"].map((child) => ({
            ...(child ? { path: child } : { index: true as const }),
            lazy: async () => ({ Component: (await import("@/features/meetings/LegacyModuleRedirect")).LegacyModuleRedirect }),
          })),
        })),
        // --- fin meetings ---
        // --- ai --- structuration automatique des projets (Genesis, propositions IA, imports, copilote)
        {
          path: "projects",
          handle: { crumb: "Projets" },
          children: [
            { path: "genesis", handle: { crumb: "Créer avec l'IA" }, lazy: async () => ({ Component: (await import("@/features/ai/GenesisPage")).GenesisPage }) },
            { path: ":id/ai-proposals", handle: { crumb: "Propositions IA" }, lazy: async () => ({ Component: (await import("@/features/ai/ProposalsPages")).ProjectProposalsPage }) },
            { path: ":id/copilot", handle: { crumb: "Copilote IA" }, lazy: async () => ({ Component: (await import("@/features/ai/CopilotPage")).CopilotPage }) },
          ],
        },
        {
          path: "ai-proposals",
          handle: { crumb: "Propositions IA" },
          children: [
            { index: true, lazy: async () => ({ Component: (await import("@/features/ai/ProposalsPages")).ProposalListPage }) },
            { path: ":id", handle: { crumb: "Aperçu" }, lazy: async () => ({ Component: (await import("@/features/ai/ProposalDetailPage")).ProposalDetailPage }) },
          ],
        },
        {
          path: "imports",
          handle: { crumb: "Imports documentaires" },
          children: [
            { index: true, lazy: async () => ({ Component: (await import("@/features/ai/ImportsPages")).ImportsPage }) },
            // --- pilotage --- assistant d'import du classeur de suivi (déclaré avant « :id »)
            { path: "tracking", handle: { crumb: "Suivi Excel" }, lazy: async () => ({ Component: (await import("@/features/pilotage/TrackingImportPage")).TrackingImportsPage }) },
            { path: "tracking/:id", handle: { crumb: "Assistant d'import" }, lazy: async () => ({ Component: (await import("@/features/pilotage/TrackingImportPage")).TrackingImportWizardPage }) },
            // --- fin pilotage ---
            { path: ":id", handle: { crumb: "Document" }, lazy: async () => ({ Component: (await import("@/features/ai/ImportsPages")).ImportDetailPage }) },
          ],
        },
        // --- pilotage --- Suivi Pôle Développement
        { path: "pilotage/suivi", handle: { crumb: "Suivi Pôle Développement" }, lazy: async () => ({ Component: (await import("@/features/pilotage/PilotagePage")).PilotagePage }) },
        // --- fin pilotage ---
        // Anciennes pages génériques (pont en lecture seule) → écrans dédiés ; « …/:id/edit » reste au pont.
        {
          path: "m/ai-proposal",
          children: [
            { index: true, lazy: async () => ({ Component: (await import("@/features/ai/LegacyRedirect")).AIModuleRedirect }) },
            { path: ":id", lazy: async () => ({ Component: (await import("@/features/ai/LegacyRedirect")).AIModuleRedirect }) },
          ],
        },
        {
          path: "m/project-import",
          children: [
            { index: true, lazy: async () => ({ Component: (await import("@/features/ai/LegacyRedirect")).AIModuleRedirect }) },
            { path: "new", lazy: async () => ({ Component: (await import("@/features/ai/LegacyRedirect")).AIModuleRedirect }) },
            { path: ":id", lazy: async () => ({ Component: (await import("@/features/ai/LegacyRedirect")).AIModuleRedirect }) },
          ],
        },
        // --- fin ai ---
        { path: "*", element: <NotFound /> },
      ],
    },
  ],
  { basename: "/app" },
);
