from rest_framework.pagination import PageNumberPagination


class FlexiblePagination(PageNumberPagination):
    """25 par défaut (inchangé) ; ``?page_size=`` jusqu'à 500 (Kanban, vue mensuelle React)."""

    page_size_query_param = "page_size"
    max_page_size = 500
