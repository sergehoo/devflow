import { isRouteErrorResponse, Link, useRouteError } from "react-router";
import { DevFlowLogo } from "@/components/brand/DevFlowLogo";
import { Button } from "@/components/ui/button";

export function RouteError() {
  const error = useRouteError();
  const message = isRouteErrorResponse(error) ? `${error.status} — ${error.statusText}` : "Une erreur inattendue est survenue.";
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 text-center">
      <DevFlowLogo variant="symbol" size={72} title={null} className="mb-2" />
      <h1 className="font-serif text-3xl font-semibold">Oups</h1>
      <p className="text-sm text-muted-foreground">{message}</p>
      <Button asChild variant="outline"><Link to="/">Retour à l'accueil</Link></Button>
    </div>
  );
}

export function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 text-center">
      <DevFlowLogo variant="symbol" size={72} title={null} className="mb-2" />
      <p className="font-serif text-6xl font-semibold text-brand">404</p>
      <p className="text-sm text-muted-foreground">Cette page n'existe pas (encore) dans la nouvelle interface.</p>
      <Button asChild variant="outline"><Link to="/">Retour à l'accueil</Link></Button>
    </div>
  );
}

