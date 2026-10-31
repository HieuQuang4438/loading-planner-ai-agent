// Infinite-looking ground grid drawn in a shader: 1 m minor and 5 m major lines, anti-aliased with `fwidth` so a
// line keeps about one pixel at any distance and angle, faded out with the distance to the camera. A ShaderMaterial skips
// the colour-space step, so the two line colours are already the light values wanted on screen.
// The login page cannot load this file (it loads nothing but style.css from the app) and carries its own copy of the
// shader: keep the two in step (tests/web/test_grid_shader.py compares the vertex shader and line(); the colours, the
// fade distances and the alpha are the login panel's own).
import * as THREE from 'three';

export const GRID_MINOR = 0xe2e8f0, GRID_MAJOR = 0xcbd5e1;

export function groundGrid({ size = 400, fade = 45 } = {}) {
  const material = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false,
    uniforms: { uCam: { value: new THREE.Vector3() }, uFade: { value: fade },
                uMinor: { value: new THREE.Color(GRID_MINOR) }, uMajor: { value: new THREE.Color(GRID_MAJOR) } },
    vertexShader: `varying vec3 vWorld;
      void main() { vec4 w = modelMatrix * vec4(position, 1.0); vWorld = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }`,
    fragmentShader: `varying vec3 vWorld; uniform vec3 uCam; uniform float uFade; uniform vec3 uMinor; uniform vec3 uMajor;
      float line(vec2 p, float size) { vec2 c = p / size; vec2 g = abs(fract(c - 0.5) - 0.5) / fwidth(c); return 1.0 - min(min(g.x, g.y), 1.0); }
      void main() {
        vec2 p = vWorld.xz;
        float minor = line(p, 1.0), major = line(p, 5.0);
        float fade = 1.0 - smoothstep(uFade * 0.35, uFade, distance(uCam.xz, p));
        float a = max(minor * 0.55, major * 0.9) * fade;
        if (a < 0.01) discard;
        gl_FragColor = vec4(mix(uMinor, uMajor, major), a);
      }`,
  });
  const grid = new THREE.Mesh(new THREE.PlaneGeometry(size, size), material);
  grid.rotation.x = -Math.PI / 2;
  grid.renderOrder = -1;
  grid.onBeforeRender = (r, s, cam) => { material.uniforms.uCam.value.copy(cam.position); };
  return grid;
}
