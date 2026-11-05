import { zodResolver } from "@hookform/resolvers/zod";
import { Eye, EyeOff, Loader2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Navigate, useNavigate, useSearchParams } from "react-router";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { legacyUrl } from "@/lib/utils";
import { useLogin, useMe } from "./api";
import { safeNext } from "./safeNext";

const schema = z.object({
  login: z.string().trim().min(1, "Saisissez votre adresse email.").email("Adresse email invalide."),
  password: z.string().min(1, "Saisissez votre mot de passe."),
});
type FormValues = z.infer<typeof schema>;

export function LoginPage() {
  const { data: me } = useMe();
  const login = useLogin();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [showPassword, setShowPassword] = useState(false);
  const { register, handleSubmit, formState: { errors } } = useForm<FormValues>({ resolver: zodResolver(schema) });
  const next = safeNext(params.get("next"));

  if (me) return <Navigate to={next} replace />;

  const onSubmit = handleSubmit((values) =>
    login.mutate(values, { onSuccess: () => navigate(next, { replace: true }) }),
  );

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-md rounded-3xl border bg-card p-8 shadow-xl">
        <p className="text-[11px] font-extrabold uppercase tracking-[0.12em] text-primary">Connexion sécurisée</p>
        <h1 className="mt-2 font-serif text-3xl font-semibold text-foreground">Bienvenue sur DevFlow</h1>
        <p className="mt-2 text-sm text-muted-foreground">Connectez-vous pour retrouver vos projets, tâches et équipes.</p>

        <form onSubmit={onSubmit} noValidate className="mt-6 space-y-4">
          {login.error && (
            <p role="alert" className="rounded-xl bg-destructive/10 px-3 py-2 text-sm text-destructive">{login.error.message}</p>
          )}
          <div>
            <Label htmlFor="login">Adresse email</Label>
            <Input id="login" type="email" autoComplete="username" autoFocus placeholder="prenom.nom@entreprise.com"
                   aria-invalid={Boolean(errors.login)} aria-describedby="login-error" {...register("login")} />
            {errors.login && <p id="login-error" className="mt-1 text-xs text-destructive">{errors.login.message}</p>}
          </div>
          <div>
            <Label htmlFor="password">Mot de passe</Label>
            <div className="relative">
              <Input id="password" type={showPassword ? "text" : "password"} autoComplete="current-password" className="pr-11"
                     aria-invalid={Boolean(errors.password)} aria-describedby="password-error" {...register("password")} />
              <button type="button" onClick={() => setShowPassword((s) => !s)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-subtle-foreground hover:text-foreground"
                      aria-label={showPassword ? "Masquer le mot de passe" : "Afficher le mot de passe"}>
                {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </button>
            </div>
            {errors.password && <p id="password-error" className="mt-1 text-xs text-destructive">{errors.password.message}</p>}
          </div>
          <div className="flex justify-end">
            <a href={legacyUrl("/accounts/password/reset/")} className="text-sm font-semibold text-primary hover:underline">
              Mot de passe oublié ?
            </a>
          </div>
          <Button type="submit" size="lg" className="w-full" disabled={login.isPending}>
            {login.isPending && <Loader2 className="animate-spin" />} {login.isPending ? "Connexion…" : "Se connecter"}
          </Button>
        </form>
      </div>
    </div>
  );
}
