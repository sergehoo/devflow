import random
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from faker import Faker
from django.utils import timezone
from project.models import TimesheetEntry, ProjectExpense, ProjectEstimateLine, ProjectBudget, Task, ProjectMember, \
    Project, TeamMembership, Team, Workspace, Sprint, ProjectRevenue

fake = Faker()
User = get_user_model()


class Command(BaseCommand):
    help = "Seed DevFlow data"

    def handle(self, *args, **kwargs):
        self.stdout.write("🚀 Seeding DevFlow data...")

        users = self.create_users(10)
        workspace = self.create_workspace(users)
        teams = self.create_teams(workspace, users)
        self.create_memberships(workspace, teams, users)

        projects = self.create_projects(workspace, teams, users)

        for project in projects:
            sprints = self.create_sprints(project, workspace)
            tasks = self.create_tasks(project, workspace, sprints, users)
            self.create_project_members(project, users, teams)
            self.create_budget(project)
            self.create_estimates(project)
            self.create_revenues(project)
            self.create_expenses(project, tasks)

        self.create_timesheets(users, workspace, projects)

        self.stdout.write(self.style.SUCCESS("✅ Seed completed"))

    # ─────────────────────────────
    # USERS
    # ─────────────────────────────
    def create_users(self, n=10):
        users = []
        for i in range(n):
            user, _ = User.objects.get_or_create(
                username=f"user{i}",
                defaults={
                    "email": fake.email(),
                },
            )
            users.append(user)
        return users

    # ─────────────────────────────
    # WORKSPACE
    # ─────────────────────────────
    def create_workspace(self, users):
        return Workspace.objects.create(
            name="DevFlow Workspace",
            owner=random.choice(users),
            description=fake.text(),
        )

    # ─────────────────────────────
    # TEAMS
    # ─────────────────────────────
    def create_teams(self, workspace, users):
        teams = []
        for name in ["Backend", "Frontend", "DevOps", "QA"]:
            team = Team.objects.create(
                workspace=workspace,
                name=name,
                lead=random.choice(users),
            )
            teams.append(team)
        return teams

    # ─────────────────────────────
    # MEMBERSHIPS
    # ─────────────────────────────
    def create_memberships(self, workspace, teams, users):
        for user in users:
            TeamMembership.objects.create(
                workspace=workspace,
                user=user,
                team=random.choice(teams),
                role=random.choice(TeamMembership.Role.values),
            )

    # ─────────────────────────────
    # PROJECTS
    # ─────────────────────────────
    def create_projects(self, workspace, teams, users):
        projects = []
        for i in range(3):
            project = Project.objects.create(
                workspace=workspace,
                name=fake.company(),
                team=random.choice(teams),
                owner=random.choice(users),
                status=random.choice(Project.Status.values),
                progress_percent=random.randint(0, 100),
                start_date=fake.date_this_year(),
                target_date=fake.date_this_year(),
            )
            projects.append(project)
        return projects

    # ─────────────────────────────
    # PROJECT MEMBERS
    # ─────────────────────────────
    def create_project_members(self, project, users, teams):
        for user in random.sample(users, 5):
            ProjectMember.objects.create(
                project=project,
                user=user,
                team=random.choice(teams),
                allocation_percent=random.randint(50, 100),
            )

    # ─────────────────────────────
    # SPRINTS
    # ─────────────────────────────
    def create_sprints(self, project, workspace):
        sprints = []
        for i in range(2):
            sprint = Sprint.objects.create(
                workspace=workspace,
                project=project,
                name=f"Sprint {i+1}",
                number=i + 1,
                start_date=timezone.now().date(),
                end_date=timezone.now().date() + timezone.timedelta(days=14),
            )
            sprints.append(sprint)
        return sprints

    # ─────────────────────────────
    # TASKS
    # ─────────────────────────────
    def create_tasks(self, project, workspace, sprints, users):
        tasks = []
        for i in range(20):
            task = Task.objects.create(
                workspace=workspace,
                project=project,
                sprint=random.choice(sprints),
                title=fake.sentence(),
                status=random.choice(Task.Status.values),
                priority=random.choice(Task.Priority.values),
                assignee=random.choice(users),
                reporter=random.choice(users),
                progress_percent=random.randint(0, 100),
                estimate_hours=Decimal(random.randint(1, 20)),
                spent_hours=Decimal(random.randint(0, 20)),
            )
            tasks.append(task)
        return tasks

    # ─────────────────────────────
    # BUDGET
    # ─────────────────────────────
    def create_budget(self, project):
        ProjectBudget.objects.create(
            project=project,
            estimated_labor_cost=Decimal(random.randint(100000, 500000)),
            estimated_infra_cost=Decimal(random.randint(50000, 200000)),
            contingency_amount=Decimal(50000),
            markup_percent=Decimal(20),
        )

    # ─────────────────────────────
    # ESTIMATE LINES
    # ─────────────────────────────
    def create_estimates(self, project):
        for i in range(5):
            ProjectEstimateLine.objects.create(
                project=project,
                label=fake.job(),
                quantity=Decimal(random.randint(5, 20)),
                cost_unit_amount=Decimal(random.randint(50000, 150000)),
                markup_percent=Decimal(20),
            )

    # ─────────────────────────────
    # REVENUES
    # ─────────────────────────────
    def create_revenues(self, project):
        for i in range(3):
            ProjectRevenue.objects.create(
                project=project,
                title=f"Paiement {i+1}",
                amount=Decimal(random.randint(200000, 1000000)),
                expected_date=fake.date_this_year(),
            )

    # ─────────────────────────────
    # EXPENSES
    # ─────────────────────────────
    def create_expenses(self, project, tasks):
        for i in range(5):
            ProjectExpense.objects.create(
                project=project,
                task=random.choice(tasks),
                title=fake.word(),
                amount=Decimal(random.randint(20000, 100000)),
                created_by=None,
            )

    # ─────────────────────────────
    # TIMESHEETS
    # ─────────────────────────────
    def create_timesheets(self, users, workspace, projects):
        for user in users:
            for _ in range(10):
                TimesheetEntry.objects.create(
                    user=user,
                    workspace=workspace,
                    project=random.choice(projects),
                    hours=Decimal(random.randint(1, 8)),
                    entry_date=fake.date_this_month(),
                )