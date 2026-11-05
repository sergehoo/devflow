import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";
import { FakeWebSocket } from "./fakeSocket";

// Le hub temps réel capture WebSocket au chargement : jamais de vraie connexion en test.
globalThis.WebSocket = FakeWebSocket as unknown as typeof WebSocket;

// Suites lancées en parallèle (jsdom + rendu paresseux) : 1 s par défaut est trop court sous charge CPU.
configure({ asyncUtilTimeout: 5000 });
