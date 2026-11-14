import {
  BarChart3, Briefcase, CalendarDays, CheckSquare, Gauge, LayoutDashboard, LifeBuoy, MessageSquare, Settings, Sun, Users,
  type LucideIcon,
} from "lucide-react";
import { can } from "@/lib/permissions";
import type { Me } from "@/types/auth";

/**
 * Navigation (miroir de la sidebar Django simplifiée).
 * `to` = page React migrée ; `legacy` = page encore servie par l'ancien frontend.
 * Les droits ne sont qu'un filtre d'affichage : Django reste l'autorité.
 */
export interface NavItem {
  label: string;
  to?: string;
  legacy?: string | ((me: Me) => string | null);
  visible?: (me: Me) => boolean;
}

export interface NavGroup {
  label: string;
  icon: LucideIcon;
  to?: string;
  legacy?: string;
  items?: NavItem[];
  visible?: (me: Me) => boolean;
}

const anyOf = (...actions: string[]) => (me: Me) => actions.some((a) => can(me.permissions, a));
const superuser = (me: Me) => me.is_superuser;

export const NAVIGATION: NavGroup[] = [
  { label: "Tableau de bord", icon: LayoutDashboard, to: "/" },
  { label: "Ma journée", icon: Sun, to: "/my-day" },
  { label: "Messagerie", icon: MessageSquare, to: "/messenger" },
  {
    label: "Projets", icon: Briefcase, items: [
      { label: "Projets", to: "/projects" },
      { label: "Roadmaps", to: "/m/roadmap" },
      { label: "Jalons", to: "/m/milestone" },
      { label: "Releases", to: "/m/release" },
      { label: "Objectifs & OKR", to: "/m/objective" },
      { label: "Risques", to: "/m/risk" },
      { label: "Analyses & suggestions IA", to: "/m/ai-insight" },
      { label: "Assistant IA", to: "/assistant" },
      // --- ai ---
      { label: "Créer un projet avec l'IA", to: "/projects/genesis" },
      { label: "Propositions IA", to: "/ai-proposals" },
      { label: "Imports documentaires", to: "/imports" },
      // --- fin ai ---
    ],
  },
  // --- pilotage --- vue consolidée qui remplace le classeur Excel de suivi
  {
    label: "Pilotage", icon: Gauge, visible: anyOf("project.view", "task.view_assigned"), items: [
      { label: "Suivi Pôle Développement", to: "/pilotage/suivi" },
    ],
  },
  // --- fin pilotage ---
  {
    label: "Exécution", icon: CheckSquare, items: [
      { label: "Tâches", to: "/tasks" },
      { label: "Backlog", to: "/m/backlog-item" },
      { label: "Sprints", to: "/m/sprint" },
      { label: "Pull requests", to: "/m/pull-request" },
    ],
  },
  {
    label: "Équipes & temps", icon: Users, items: [
      { label: "Équipes", to: "/teams" },
      { label: "Membres", to: "/members" },
      { label: "Mes timesheets", to: "/timesheets" },
      { label: "Feuilles de temps des collaborateurs", to: "/timesheets/sheets" },
      { label: "Validation des timesheets", to: "/timesheets/validation" },
    ],
  },
  {
    label: "Finance", icon: BarChart3, visible: anyOf("budget.view", "billing.view"), items: [
      { label: "Cockpit financier", to: "/finance/portfolio", visible: anyOf("budget.view") },
      { label: "Dépenses", to: "/m/project-expense", visible: anyOf("budget.view") },
      { label: "Allocation IA des ressources", to: "/finance/allocation", visible: anyOf("budget.view") },
      { label: "Factures", to: "/m/invoice", visible: anyOf("billing.view") },
      { label: "Clients", to: "/m/invoice-client", visible: anyOf("billing.view") },
    ],
  },
  // --- tickets ---
  {
    label: "Support", icon: LifeBuoy, visible: anyOf("ticket.view", "ticket.view_assigned"), items: [
      { label: "Ticket Center", to: "/tickets" },
      { label: "Tickets", to: "/tickets/list" },
      { label: "Applications connectées", to: "/tickets/applications", visible: anyOf("ticket.view") },
      { label: "Routage & SLA", to: "/tickets/settings", visible: anyOf("ticket.view") },
      { label: "Canaux e-mail", to: "/tickets/email", visible: anyOf("ticket.admin") },
    ],
  },
  // --- meetings ---
  {
    label: "Réunions", icon: CalendarDays, items: [
      { label: "Vue d'ensemble", to: "/meetings/dashboard" },
      { label: "Réunions", to: "/meetings" },
      { label: "Séries récurrentes", to: "/meetings/series" },
      { label: "Registre des décisions", to: "/meetings/decisions" },
    ],
  },
  // --- fin meetings ---
  {
    label: "Paramètres", icon: Settings, items: [
      { label: "Workspaces", to: "/workspaces", visible: superuser },
      { label: "Paramètres du workspace", to: "/m/workspace-settings", visible: superuser },
      { label: "Invitations", to: "/m/workspace-invitation", visible: superuser },
      { label: "Identité & papier en-tête", to: "/branding", visible: anyOf("billing.view") },
      { label: "Méthodologies", to: "/m/methodology", visible: superuser },
      { label: "Labels", to: "/m/label" },
      { label: "Intégrations", to: "/m/integration", visible: anyOf("integration.manage", "settings.manage") },
      { label: "Webhooks", to: "/m/webhook", visible: anyOf("integration.manage", "settings.manage") },
      { label: "Clés API", to: "/m/api-key", visible: anyOf("integration.manage", "settings.manage") },
      { label: "Journal d'activité", to: "/m/activity-log" },
    ],
  },
];

export function resolveLegacy(item: { legacy?: NavItem["legacy"] }, me: Me): string | null {
  if (!item.legacy) return null;
  return typeof item.legacy === "function" ? item.legacy(me) : item.legacy;
}
