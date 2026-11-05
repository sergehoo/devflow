/** Réponse paginée DRF (PageNumberPagination, PAGE_SIZE 25). */
export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
