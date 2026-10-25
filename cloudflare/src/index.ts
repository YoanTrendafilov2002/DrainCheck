import { Container, ContainerProxy, getContainer } from '@cloudflare/containers';
import { INSTANCE_NAME, STATE_HOST, routeRequest, readinessGate } from './routing.mjs';
import { stateRequest } from './state-store.mjs';

interface Env {
  ASSETS: Fetcher;
  DRAINCHECK: DurableObjectNamespace<DrainCheckContainer>;
  DRAINCHECK_STATE: R2Bucket;
}

// Required by the SDK for the private outbound binding. This is a Worker
// entrypoint used by the container platform, not a public URL route.
export { ContainerProxy };

export class DrainCheckContainer extends Container<Env> {
  defaultPort = 8080;
  sleepAfter = '10m';
  enableInternet = false;
  allowedHosts = [STATE_HOST];
  envVars = {
    DRAINCHECK_STATE_URL: `http://${STATE_HOST}`,
    PROJ_NETWORK: 'OFF',
  };

  // Real source verification may read several GB at startup. The SDK's default
  // twenty-second port timeout is too short for that genuine verification.
  private ready = readinessGate(() => this.startAndWaitForPorts({
    ports: [8080],
    cancellationOptions: { instanceGetTimeoutMS: 30_000, portReadyTimeoutMS: 240_000 },
  }));

  override async fetch(request: Request): Promise<Response> {
    await this.ready();
    return this.containerFetch(request);
  }
}

DrainCheckContainer.outboundByHost = {
  [STATE_HOST]: (request: Request, env: Env) => stateRequest(request, env.DRAINCHECK_STATE),
};

export default {
  fetch(request: Request, env: Env): Promise<Response> {
    return routeRequest(request, env.ASSETS, () => getContainer(env.DRAINCHECK, INSTANCE_NAME));
  },
} satisfies ExportedHandler<Env>;
