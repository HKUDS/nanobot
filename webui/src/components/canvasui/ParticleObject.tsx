/**
 * Canvas UI Particle Object
 * Source: https://github.com/DavidHDev/canvas-ui
 * License: MIT + Commons Clause
 */
"use client";

import { useEffect, useRef, useState } from "react";

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

export interface ParticleObjectOptions {
  /** URL of the asset to display: GLB/glTF, SVG, PNG, JPEG, WebP, or GIF. Object URLs from a file input work too. The format is sniffed from the bytes, not the extension. */
  src?: string;
  /** Number of particles the asset is rebuilt from. */
  count?: number;
  /** Particle size in CSS pixels at the model's distance. */
  size?: number;
  /** Random per-particle size variation (0 to 1). */
  sizeVariance?: number;
  /** Override color as any CSS color. Empty string keeps the asset's own colors. */
  color?: string;
  /** Radius of the cursor's push field in CSS pixels. */
  radius?: number;
  /** How hard the cursor pushes particles away. */
  strength?: number;
  /** Tangential curl of the push (0 to 2). Particles spiral around the cursor instead of only fleeing it. */
  swirl?: number;
  /** How quickly displaced particles spring back home. */
  spring?: number;
  /** Velocity damping (0 to 1). Lower values keep particles wobbling longer. */
  damping?: number;
  /** Idle shimmer of the resting particles (0 disables). */
  drift?: number;
  /** Background color behind the particles. Empty string keeps the canvas transparent. */
  background?: string;
  /** Size of the longest side of the asset in scene units. The camera sits about 4 units away. */
  scale?: number;
  /** Horizontal offset of the asset in scene units. */
  xOffset?: number;
  /** Vertical offset of the asset in scene units. */
  yOffset?: number;
  /** Strength of the floating bob animation (0 disables). */
  floatIntensity?: number;
  /** Strength of the idle rocking rotation (0 disables). */
  rotationIntensity?: number;
  /** Speed of the float and rocking animation. */
  floatSpeed?: number;
  /** Let the user orbit the camera by dragging. */
  orbit?: boolean;
  /** Let the user zoom with the scroll wheel or pinch. */
  zoom?: boolean;
  /** Spin the camera around the asset turntable-style. */
  autoRotate?: boolean;
  /** Turntable speed when autoRotate is on. */
  autoRotateSpeed?: number;
  /** Camera field of view in degrees. */
  fov?: number;
  /** Camera distance from the center of the asset. */
  cameraDistance?: number;
  /** Base URL of the Draco decoder, fetched only when a model needs it. */
  dracoDecoderPath?: string;
  /** Called after an asset finishes loading. */
  onLoad?: (() => void) | null;
  /** Called when an asset fails to load. */
  onError?: ((error: unknown) => void) | null;
}

export interface ParticleObjectElements {
  /** Canvas the scene renders to. */
  canvas: HTMLCanvasElement;
}

export interface ParticleObjectInstance {
  /** Update options live. Changing src loads the new asset. */
  setOptions: (options: ParticleObjectOptions) => void;
  /** Re-read canvas size. Call when the element is resized. */
  resize: () => void;
  /** Stop the loop and release all GPU resources. */
  destroy: () => void;
}

const DEFAULTS: Required<ParticleObjectOptions> = {
  src: "",
  count: 14000,
  size: 2.4,
  sizeVariance: 0.6,
  color: "",
  radius: 110,
  strength: 1,
  swirl: 0.6,
  spring: 1,
  damping: 0.35,
  drift: 0.6,
  background: "",
  scale: 3,
  xOffset: 0,
  yOffset: 0,
  floatIntensity: 2,
  rotationIntensity: 1,
  floatSpeed: 2,
  orbit: true,
  zoom: false,
  autoRotate: false,
  autoRotateSpeed: 2,
  fov: 65,
  cameraDistance: 4.2,
  dracoDecoderPath: "https://www.gstatic.com/draco/versioned/decoders/1.5.7/",
  onLoad: null,
  onError: null,
};

const CAMERA_DIR = new THREE.Vector3(0, -1, 4).normalize();
const MODEL_LIFT = 0.3;
const RASTER_SIZE = 420;
const ALBEDO_SIZE = 128;

const VERT = `
in vec3 aColor;
in float aShade;
in float aSeed;
out vec3 vColor;
uniform float uTime;
uniform float uDrift;
uniform float uSize;
uniform float uVariance;
uniform float uDpr;
uniform float uRefDist;
uniform vec3 uTint;
uniform float uUseTint;

void main() {
  vec3 p = position;

  float t = uTime + aSeed * 39.0;
  p += uDrift * 0.005 * vec3(
    sin(t * 1.7 + aSeed * 61.0),
    cos(t * 1.3 + aSeed * 23.0),
    sin(t * 2.3 + aSeed * 47.0));
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  float jitter = 1.0 + uVariance * (fract(aSeed * 7.13) - 0.5) * 1.4;
  gl_PointSize = clamp(
    uSize * uDpr * jitter * (uRefDist / max(-mv.z, 0.1)), 0.0, 64.0);
  vColor = mix(aColor, uTint * aShade, uUseTint);
  gl_Position = projectionMatrix * mv;
}`;

const FRAG = `
precision highp float;
in vec3 vColor;
out vec4 outColor;

void main() {
  vec2 c = gl_PointCoord - 0.5;
  float r2 = dot(c, c);
  float alpha = 1.0 - smoothstep(0.16, 0.25, r2);
  if (alpha < 0.08) discard;
  outColor = vec4(vColor, alpha);
}`;

interface CloudSample {
  positions: Float32Array;
  colors: Float32Array;
  shades: Float32Array;
}

interface MeshSource {
  kind: "mesh";
  scene: THREE.Group;
}

interface ImageSource {
  kind: "image";
  data: ImageData;
}

type AssetSource = MeshSource | ImageSource;

interface TriangleBucket {
  positions: THREE.BufferAttribute | THREE.InterleavedBufferAttribute;
  normals: THREE.BufferAttribute | THREE.InterleavedBufferAttribute | null;
  uvs: THREE.BufferAttribute | THREE.InterleavedBufferAttribute | null;
  vertexColors: THREE.BufferAttribute | THREE.InterleavedBufferAttribute | null;
  index: THREE.BufferAttribute | null;
  matrix: THREE.Matrix4;
  normalMatrix: THREE.Matrix3;
  baseColor: THREE.Color;
  albedo: ImageData | null;
  albedoFlipY: boolean;
  triangleCount: number;
}

function disposeObject(root: THREE.Object3D) {
  root.traverse((node) => {
    const mesh = node as THREE.Mesh;
    if (mesh.geometry) mesh.geometry.dispose();
    const materials = Array.isArray(mesh.material)
      ? mesh.material
      : [mesh.material];
    for (const material of materials) {
      if (!material) continue;
      for (const value of Object.values(material)) {
        if (value instanceof THREE.Texture) value.dispose();
      }
      material.dispose();
    }
  });
}

function readAlbedo(map: THREE.Texture | null): ImageData | null {
  const image = map?.image as
    HTMLImageElement | HTMLCanvasElement | ImageBitmap | undefined;
  if (!image || !image.width || !image.height) return null;
  try {
    const ratio = Math.min(
      1,
      ALBEDO_SIZE / Math.max(image.width, image.height),
    );
    const width = Math.max(1, Math.round(image.width * ratio));
    const height = Math.max(1, Math.round(image.height * ratio));
    const scratch = document.createElement("canvas");
    scratch.width = width;
    scratch.height = height;
    const ctx = scratch.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(image, 0, 0, width, height);
    return ctx.getImageData(0, 0, width, height);
  } catch {
    return null;
  }
}

function sampleAlbedo(
  data: ImageData,
  u: number,
  v: number,
  flipY: boolean,
  out: THREE.Color,
) {
  const x = Math.min(
    data.width - 1,
    Math.max(0, Math.floor((u - Math.floor(u)) * data.width)),
  );
  const vWrapped = v - Math.floor(v);
  const y = Math.min(
    data.height - 1,
    Math.max(0, Math.floor((flipY ? 1 - vWrapped : vWrapped) * data.height)),
  );
  const i = (y * data.width + x) * 4;
  out.setRGB(
    data.data[i] / 255,
    data.data[i + 1] / 255,
    data.data[i + 2] / 255,
    THREE.SRGBColorSpace,
  );
}

function sampleMesh(scene: THREE.Group, count: number): CloudSample {
  scene.updateMatrixWorld(true);
  const buckets: TriangleBucket[] = [];

  scene.traverse((node) => {
    const mesh = node as THREE.Mesh;
    if (!mesh.isMesh) return;
    const geometry = mesh.geometry as THREE.BufferGeometry;
    const positions = geometry.getAttribute("position");
    if (!positions) return;
    const index = geometry.getIndex();
    const triangleCount = Math.floor(
      (index ? index.count : positions.count) / 3,
    );
    if (triangleCount === 0) return;
    const material = (
      Array.isArray(mesh.material) ? mesh.material[0] : mesh.material
    ) as THREE.MeshStandardMaterial;
    buckets.push({
      positions,
      normals: geometry.getAttribute("normal") ?? null,
      uvs: geometry.getAttribute("uv") ?? null,
      vertexColors: geometry.getAttribute("color") ?? null,
      index,
      matrix: mesh.matrixWorld.clone(),
      normalMatrix: new THREE.Matrix3().getNormalMatrix(mesh.matrixWorld),
      baseColor: material?.color?.clone() ?? new THREE.Color(1, 1, 1),
      albedo: readAlbedo(material?.map ?? null),
      albedoFlipY: material?.map?.flipY ?? false,
      triangleCount,
    });
  });

  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const shades = new Float32Array(count);
  if (buckets.length === 0) return { positions, colors, shades };

  const areas: number[] = [];
  const owners: { bucket: TriangleBucket; tri: number }[] = [];
  const a = new THREE.Vector3();
  const b = new THREE.Vector3();
  const c = new THREE.Vector3();
  const ab = new THREE.Vector3();
  const ac = new THREE.Vector3();
  let totalArea = 0;

  const vertexIndex = (bucket: TriangleBucket, tri: number, corner: number) =>
    bucket.index ? bucket.index.getX(tri * 3 + corner) : tri * 3 + corner;

  for (const bucket of buckets) {
    for (let tri = 0; tri < bucket.triangleCount; tri++) {
      const i0 = vertexIndex(bucket, tri, 0);
      const i1 = vertexIndex(bucket, tri, 1);
      const i2 = vertexIndex(bucket, tri, 2);
      a.fromBufferAttribute(bucket.positions, i0).applyMatrix4(bucket.matrix);
      b.fromBufferAttribute(bucket.positions, i1).applyMatrix4(bucket.matrix);
      c.fromBufferAttribute(bucket.positions, i2).applyMatrix4(bucket.matrix);
      ab.subVectors(b, a);
      ac.subVectors(c, a);
      totalArea += ab.cross(ac).length() * 0.5;
      areas.push(totalArea);
      owners.push({ bucket, tri });
    }
  }
  if (totalArea <= 0) return { positions, colors, shades };

  const normal = new THREE.Vector3();
  const albedo = new THREE.Color();
  const texel = new THREE.Color();
  const final = new THREE.Color();
  const light = new THREE.Vector3(0.5, 0.8, 0.6).normalize();

  for (let i = 0; i < count; i++) {
    const pick = Math.random() * totalArea;
    let lo = 0;
    let hi = areas.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (areas[mid] < pick) lo = mid + 1;
      else hi = mid;
    }
    const { bucket, tri } = owners[lo];
    const i0 = vertexIndex(bucket, tri, 0);
    const i1 = vertexIndex(bucket, tri, 1);
    const i2 = vertexIndex(bucket, tri, 2);

    let u = Math.random();
    let v = Math.random();
    if (u + v > 1) {
      u = 1 - u;
      v = 1 - v;
    }
    const w = 1 - u - v;

    a.fromBufferAttribute(bucket.positions, i0);
    b.fromBufferAttribute(bucket.positions, i1);
    c.fromBufferAttribute(bucket.positions, i2);
    a.multiplyScalar(w).addScaledVector(b, u).addScaledVector(c, v);
    a.applyMatrix4(bucket.matrix);
    positions[i * 3] = a.x;
    positions[i * 3 + 1] = a.y;
    positions[i * 3 + 2] = a.z;

    albedo.copy(bucket.baseColor);
    if (bucket.albedo && bucket.uvs) {
      const tu =
        bucket.uvs.getX(i0) * w +
        bucket.uvs.getX(i1) * u +
        bucket.uvs.getX(i2) * v;
      const tv =
        bucket.uvs.getY(i0) * w +
        bucket.uvs.getY(i1) * u +
        bucket.uvs.getY(i2) * v;
      sampleAlbedo(bucket.albedo, tu, tv, bucket.albedoFlipY, texel);
      albedo.multiply(texel);
    }
    if (bucket.vertexColors) {
      albedo.multiplyScalar(
        (bucket.vertexColors.getX(i0) * w +
          bucket.vertexColors.getX(i1) * u +
          bucket.vertexColors.getX(i2) * v +
          bucket.vertexColors.getY(i0) * w +
          bucket.vertexColors.getY(i1) * u +
          bucket.vertexColors.getY(i2) * v +
          bucket.vertexColors.getZ(i0) * w +
          bucket.vertexColors.getZ(i1) * u +
          bucket.vertexColors.getZ(i2) * v) /
          3,
      );
    }

    let shade = 0.85;
    if (bucket.normals) {
      normal.set(
        bucket.normals.getX(i0) * w +
          bucket.normals.getX(i1) * u +
          bucket.normals.getX(i2) * v,
        bucket.normals.getY(i0) * w +
          bucket.normals.getY(i1) * u +
          bucket.normals.getY(i2) * v,
        bucket.normals.getZ(i0) * w +
          bucket.normals.getZ(i1) * u +
          bucket.normals.getZ(i2) * v,
      );
      normal.applyMatrix3(bucket.normalMatrix).normalize();
      shade = 0.45 + 0.65 * Math.max(normal.dot(light) * 0.5 + 0.5, 0);
    }

    final.copy(albedo).multiplyScalar(shade);
    final.convertLinearToSRGB();
    colors[i * 3] = Math.min(final.r, 1);
    colors[i * 3 + 1] = Math.min(final.g, 1);
    colors[i * 3 + 2] = Math.min(final.b, 1);
    shades[i] = Math.min(Math.pow(shade, 1 / 2.2), 1);
  }

  return { positions, colors, shades };
}

function sampleImage(data: ImageData, count: number): CloudSample {
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const shades = new Float32Array(count);

  const pixels: number[] = [];
  const weights: number[] = [];
  let totalWeight = 0;
  for (let i = 0; i < data.width * data.height; i++) {
    const alpha = data.data[i * 4 + 3];
    if (alpha < 10) continue;
    totalWeight += alpha;
    pixels.push(i);
    weights.push(totalWeight);
  }
  if (pixels.length === 0) return { positions, colors, shades };

  const longest = Math.max(data.width, data.height);
  for (let i = 0; i < count; i++) {
    const pick = Math.random() * totalWeight;
    let lo = 0;
    let hi = weights.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (weights[mid] < pick) lo = mid + 1;
      else hi = mid;
    }
    const p = pixels[lo];
    const px = p % data.width;
    const py = Math.floor(p / data.width);
    positions[i * 3] = (px + Math.random() - data.width / 2) / longest;
    positions[i * 3 + 1] = -(py + Math.random() - data.height / 2) / longest;
    positions[i * 3 + 2] = (Math.random() - 0.5) * 0.02;
    colors[i * 3] = data.data[p * 4] / 255;
    colors[i * 3 + 1] = data.data[p * 4 + 1] / 255;
    colors[i * 3 + 2] = data.data[p * 4 + 2] / 255;
    shades[i] = 1;
  }

  return { positions, colors, shades };
}

function normalizeCloud(sample: CloudSample) {
  const p = sample.positions;
  if (p.length === 0) return;
  let minX = Infinity,
    minY = Infinity,
    minZ = Infinity;
  let maxX = -Infinity,
    maxY = -Infinity,
    maxZ = -Infinity;
  for (let i = 0; i < p.length; i += 3) {
    minX = Math.min(minX, p[i]);
    maxX = Math.max(maxX, p[i]);
    minY = Math.min(minY, p[i + 1]);
    maxY = Math.max(maxY, p[i + 1]);
    minZ = Math.min(minZ, p[i + 2]);
    maxZ = Math.max(maxZ, p[i + 2]);
  }
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  const cz = (minZ + maxZ) / 2;
  const inv = 1 / Math.max(maxX - minX, maxY - minY, maxZ - minZ, 1e-4);
  for (let i = 0; i < p.length; i += 3) {
    p[i] = (p[i] - cx) * inv;
    p[i + 1] = (p[i + 1] - cy) * inv;
    p[i + 2] = (p[i + 2] - cz) * inv;
  }
}

function sniffKind(
  bytes: Uint8Array,
): "glb" | "gltf" | "svg" | "bitmap" | null {
  if (bytes.length < 4) return null;
  const ascii = (start: number, text: string) => {
    for (let i = 0; i < text.length; i++) {
      if (bytes[start + i] !== text.charCodeAt(i)) return false;
    }
    return true;
  };
  if (ascii(0, "glTF")) return "glb";
  if (bytes[0] === 0x89 && ascii(1, "PNG")) return "bitmap";
  if (bytes[0] === 0xff && bytes[1] === 0xd8) return "bitmap";
  if (ascii(0, "RIFF") && ascii(8, "WEBP")) return "bitmap";
  if (ascii(0, "GIF8")) return "bitmap";
  let head: string;
  try {
    head = new TextDecoder()
      .decode(bytes.subarray(0, 2048))
      .replace(/^\uFEFF/, "")
      .trimStart();
  } catch {
    return null;
  }
  if (head.startsWith("{")) return "gltf";
  if (head.startsWith("<")) {
    return head.includes("<svg") ? "svg" : null;
  }
  return null;
}

function rasterizeImage(blob: Blob): Promise<ImageData> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(url);
      const width = image.naturalWidth || 1024;
      const height = image.naturalHeight || 1024;
      const ratio = Math.min(1, RASTER_SIZE / Math.max(width, height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(width * ratio));
      canvas.height = Math.max(1, Math.round(height * ratio));
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        reject(new Error("2d context unavailable"));
        return;
      }
      ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
      resolve(ctx.getImageData(0, 0, canvas.width, canvas.height));
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Could not decode the image"));
    };
    image.src = url;
  });
}

export function createParticleObject(
  elements: ParticleObjectElements,
  options: ParticleObjectOptions = {},
): ParticleObjectInstance | null {
  const { canvas } = elements;
  const config: Required<ParticleObjectOptions> = { ...DEFAULTS, ...options };

  let renderer: THREE.WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: false,
      alpha: true,
      powerPreference: "high-performance",
    });
  } catch {
    return null;
  }

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(config.fov, 1, 0.1, 200);
  camera.position.copy(CAMERA_DIR).multiplyScalar(config.cameraDistance);

  const floatGroup = new THREE.Group();
  floatGroup.position.y = MODEL_LIFT;
  const fitGroup = new THREE.Group();
  floatGroup.add(fitGroup);
  scene.add(floatGroup);

  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.enablePan = false;

  const material = new THREE.ShaderMaterial({
    glslVersion: THREE.GLSL3,
    vertexShader: VERT,
    fragmentShader: FRAG,
    transparent: true,
    depthWrite: true,
    uniforms: {
      uTime: { value: Math.random() * 100 },
      uDrift: { value: config.drift },
      uSize: { value: config.size },
      uVariance: { value: config.sizeVariance },
      uDpr: { value: 1 },
      uRefDist: { value: config.cameraDistance },
      uTint: { value: new THREE.Color(1, 1, 1) },
      uUseTint: { value: 0 },
    },
  });

  let points: THREE.Points | null = null;
  let homes: Float32Array | null = null;
  let velocities: Float32Array | null = null;
  let particleCount = 0;
  let assetSource: AssetSource | null = null;
  let builtCount = -1;
  let loadedSrc: string | null = null;
  let loadToken = 0;
  let disposed = false;

  const loader = new GLTFLoader();
  const draco = new DRACOLoader();
  draco.setDecoderPath(config.dracoDecoderPath);
  loader.setDRACOLoader(draco);

  function clearPoints() {
    if (!points) return;
    fitGroup.remove(points);
    points.geometry.dispose();
    points = null;
    homes = null;
    velocities = null;
    particleCount = 0;
  }

  function clearAsset() {
    if (assetSource?.kind === "mesh") disposeObject(assetSource.scene);
    assetSource = null;
    builtCount = -1;
    clearPoints();
  }

  function buildCloud() {
    if (!assetSource) return;
    const count = Math.max(Math.round(config.count), 16);
    if (count === builtCount && points) return;
    builtCount = count;
    clearPoints();

    const sample =
      assetSource.kind === "mesh"
        ? sampleMesh(assetSource.scene, count)
        : sampleImage(assetSource.data, count);
    normalizeCloud(sample);

    const seeds = new Float32Array(count);
    for (let i = 0; i < count; i++) seeds[i] = Math.random();

    const geometry = new THREE.BufferGeometry();
    const positionAttr = new THREE.BufferAttribute(sample.positions.slice(), 3);
    positionAttr.setUsage(THREE.DynamicDrawUsage);
    geometry.setAttribute("position", positionAttr);
    geometry.setAttribute(
      "aColor",
      new THREE.BufferAttribute(sample.colors, 3),
    );
    geometry.setAttribute(
      "aShade",
      new THREE.BufferAttribute(sample.shades, 1),
    );
    geometry.setAttribute("aSeed", new THREE.BufferAttribute(seeds, 1));

    homes = sample.positions;
    velocities = new Float32Array(count * 3);
    particleCount = count;
    points = new THREE.Points(geometry, material);
    points.frustumCulled = false;
    fitGroup.add(points);
  }

  async function loadAsset() {
    const src = config.src;
    if (src === loadedSrc) return;
    loadedSrc = src;
    const token = ++loadToken;
    if (!src) {
      clearAsset();
      return;
    }
    try {
      const response = await fetch(src);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const buffer = await response.arrayBuffer();
      if (disposed || token !== loadToken) return;
      const bytes = new Uint8Array(buffer);
      const kind = sniffKind(bytes);
      if (!kind) throw new Error("Unrecognized asset format");

      if (kind === "glb" || kind === "gltf") {
        draco.setDecoderPath(config.dracoDecoderPath);
        const resourcePath = src.slice(0, src.lastIndexOf("/") + 1);
        const data = kind === "glb" ? buffer : new TextDecoder().decode(bytes);
        const gltf = await loader.parseAsync(data, resourcePath);
        if (disposed || token !== loadToken) {
          disposeObject(gltf.scene);
          return;
        }
        clearAsset();
        assetSource = { kind: "mesh", scene: gltf.scene };
      } else {
        const blob = new Blob([buffer], {
          type: kind === "svg" ? "image/svg+xml" : "",
        });
        const data = await rasterizeImage(blob);
        if (disposed || token !== loadToken) return;
        clearAsset();
        assetSource = { kind: "image", data };
      }
      buildCloud();
      config.onLoad?.();
    } catch (error) {
      if (disposed || token !== loadToken) return;
      config.onError?.(error);
    }
  }

  const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  let reducedMotion = motionQuery.matches;
  const onMotionChange = () => {
    reducedMotion = motionQuery.matches;
    if (reducedMotion) floatGroup.rotation.set(0, 0, 0);
    applyOptions();
  };
  motionQuery.addEventListener("change", onMotionChange);

  const tint = new THREE.Color();

  function applyOptions() {
    renderer.setClearColor(
      new THREE.Color(config.background || "#000000"),
      config.background ? 1 : 0,
    );
    controls.enableRotate = config.orbit;
    controls.enableZoom = config.zoom;
    controls.autoRotate = config.autoRotate && !reducedMotion;
    controls.autoRotateSpeed = config.autoRotateSpeed;
    camera.fov = config.fov;
    camera.updateProjectionMatrix();
    floatGroup.position.x = config.xOffset;
    floatGroup.position.y = MODEL_LIFT + config.yOffset;
    fitGroup.scale.setScalar(config.scale);
    material.uniforms.uDrift.value = reducedMotion
      ? 0
      : Math.max(config.drift, 0);
    material.uniforms.uSize.value = Math.max(config.size, 0.1);
    material.uniforms.uVariance.value = Math.min(
      Math.max(config.sizeVariance, 0),
      1,
    );
    material.uniforms.uRefDist.value = config.cameraDistance;
    if (config.color) {
      tint.set(config.color);
      (material.uniforms.uTint.value as THREE.Color).copy(tint);
      material.uniforms.uUseTint.value = 1;
    } else {
      material.uniforms.uUseTint.value = 0;
    }
  }

  function resize() {
    const width = Math.max(canvas.clientWidth, 1);
    const height = Math.max(canvas.clientHeight, 1);
    const pr = Math.min(window.devicePixelRatio || 1, 2);
    renderer.setPixelRatio(pr);
    renderer.setSize(width, height, false);
    material.uniforms.uDpr.value = pr;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  const observer = new ResizeObserver(resize);
  observer.observe(canvas);
  resize();
  applyOptions();
  loadAsset();

  let pointerX = 0;
  let pointerY = 0;
  let pointerActive = false;
  let pointerSpeed = 0;
  let lastPointerX = 0;
  let lastPointerY = 0;
  let lastPointerTime = 0;
  let shoveX = 0;
  let shoveY = 0;

  function onPointerMove(event: PointerEvent) {
    const rect = canvas.getBoundingClientRect();
    pointerX = event.clientX - rect.left;
    pointerY = event.clientY - rect.top;
    const now = performance.now();
    if (pointerActive && lastPointerTime) {
      const dt = Math.max((now - lastPointerTime) / 1000, 1e-3);
      const dx = pointerX - lastPointerX;
      const dy = pointerY - lastPointerY;
      const speed = Math.hypot(dx, dy) / dt;
      pointerSpeed += (speed - pointerSpeed) * 0.35;
      if (speed > 1) {
        const inv = 1 / Math.max(Math.hypot(dx, dy), 1e-3);
        shoveX += (dx * inv - shoveX) * 0.4;
        shoveY += (dy * inv - shoveY) * 0.4;
      }
    }
    lastPointerX = pointerX;
    lastPointerY = pointerY;
    lastPointerTime = now;
    pointerActive = true;
  }

  function onPointerLeave() {
    pointerActive = false;
    pointerSpeed = 0;
    lastPointerTime = 0;
  }

  canvas.addEventListener("pointerdown", onPointerMove, { passive: true });
  canvas.addEventListener("pointermove", onPointerMove, { passive: true });
  canvas.addEventListener("pointerup", onPointerLeave, { passive: true });
  canvas.addEventListener("pointerleave", onPointerLeave, { passive: true });
  canvas.addEventListener("pointercancel", onPointerLeave, { passive: true });

  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  const inverseMatrix = new THREE.Matrix4();
  const localOrigin = new THREE.Vector3();
  const localDir = new THREE.Vector3();
  const camRight = new THREE.Vector3();
  const camUp = new THREE.Vector3();
  const camBack = new THREE.Vector3();
  const localShove = new THREE.Vector3();

  function simulate(delta: number) {
    if (!points || !homes || !velocities || particleCount === 0) return;
    const positionAttr = points.geometry.getAttribute(
      "position",
    ) as THREE.BufferAttribute;
    const p = positionAttr.array as Float32Array;
    const h = homes;
    const v = velocities;

    const stiffness = 60 * Math.max(config.spring, 0.05);
    const dampingRate = 3 + 12 * Math.min(Math.max(config.damping, 0), 1);
    const decay = Math.exp(-dampingRate * delta);

    let pushing = false;
    let ox = 0,
      oy = 0,
      oz = 0,
      dx = 0,
      dy = 0,
      dz = 1;
    let localRadius = 0;
    let pushAccel = 0;
    let shove = 0;

    // Reduced motion disables ambient movement, but direct pointer input remains responsive.
    if (pointerActive && config.strength > 0) {
      const width = Math.max(canvas.clientWidth, 1);
      const height = Math.max(canvas.clientHeight, 1);
      ndc.set((pointerX / width) * 2 - 1, -(pointerY / height) * 2 + 1);
      raycaster.setFromCamera(ndc, camera);

      points.updateWorldMatrix(true, false);
      inverseMatrix.copy(points.matrixWorld).invert();
      localOrigin.copy(raycaster.ray.origin).applyMatrix4(inverseMatrix);
      localDir.copy(raycaster.ray.direction).transformDirection(inverseMatrix);

      const worldScale = Math.max(fitGroup.scale.x, 1e-4);
      const worldPerPx =
        (2 *
          camera.position.distanceTo(floatGroup.position) *
          Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2)) /
        height;
      localRadius = (Math.max(config.radius, 1) * worldPerPx) / worldScale;
      pushAccel = 26 * config.strength;
      shove = Math.min(pointerSpeed / 900, 2) * 14 * config.strength;
      camera.matrixWorld.extractBasis(camRight, camUp, camBack);
      localShove
        .set(0, 0, 0)
        .addScaledVector(camRight, shoveX)
        .addScaledVector(camUp, -shoveY)
        .transformDirection(inverseMatrix);

      ox = localOrigin.x;
      oy = localOrigin.y;
      oz = localOrigin.z;
      dx = localDir.x;
      dy = localDir.y;
      dz = localDir.z;
      pushing = true;
    }

    const swirl = Math.min(Math.max(config.swirl, 0), 2);
    const r2max = localRadius * localRadius;

    for (let i = 0; i < particleCount; i++) {
      const ix = i * 3;
      const iy = ix + 1;
      const iz = ix + 2;
      let vx = v[ix];
      let vy = v[iy];
      let vz = v[iz];

      if (pushing) {
        const wx = p[ix] - ox;
        const wy = p[iy] - oy;
        const wz = p[iz] - oz;
        const t = Math.max(wx * dx + wy * dy + wz * dz, 0);
        let rx = wx - dx * t;
        let ry = wy - dy * t;
        let rz = wz - dz * t;
        const dist2 = rx * rx + ry * ry + rz * rz;
        if (dist2 < r2max) {
          const dist = Math.sqrt(dist2);
          const inv = 1 / Math.max(dist, 1e-5);
          rx *= inv;
          ry *= inv;
          rz *= inv;
          const fall = 1 - dist / localRadius;
          const f = fall * fall * delta;
          const tx = dy * rz - dz * ry;
          const ty = dz * rx - dx * rz;
          const tz = dx * ry - dy * rx;
          vx += (rx + tx * swirl) * pushAccel * f + localShove.x * shove * f;
          vy += (ry + ty * swirl) * pushAccel * f + localShove.y * shove * f;
          vz += (rz + tz * swirl) * pushAccel * f + localShove.z * shove * f;
        }
      }

      vx += (h[ix] - p[ix]) * stiffness * delta;
      vy += (h[iy] - p[iy]) * stiffness * delta;
      vz += (h[iz] - p[iz]) * stiffness * delta;
      vx *= decay;
      vy *= decay;
      vz *= decay;
      p[ix] += vx * delta;
      p[iy] += vy * delta;
      p[iz] += vz * delta;
      v[ix] = vx;
      v[iy] = vy;
      v[iz] = vz;
    }

    positionAttr.needsUpdate = true;
  }

  let inView = true;
  const viewObserver =
    typeof IntersectionObserver !== "undefined"
      ? new IntersectionObserver((entries) => {
          inView = entries[entries.length - 1]?.isIntersecting ?? true;
        })
      : null;
  viewObserver?.observe(canvas);

  let lastTime = 0;
  let elapsed = Math.random() * 100;

  renderer.setAnimationLoop((time: number) => {
    if (!inView) {
      lastTime = 0;
      return;
    }
    const delta = lastTime ? Math.min((time - lastTime) / 1000, 1 / 30) : 0;
    lastTime = time;
    controls.update();

    if (!reducedMotion) {
      elapsed += delta * config.floatSpeed;
      floatGroup.rotation.x =
        (Math.cos(elapsed / 4) / 8) * config.rotationIntensity;
      floatGroup.rotation.y =
        (Math.sin(elapsed / 4) / 8) * config.rotationIntensity;
      floatGroup.rotation.z =
        (Math.sin(elapsed / 4) / 20) * config.rotationIntensity;
      floatGroup.position.y =
        MODEL_LIFT +
        config.yOffset +
        (Math.sin(elapsed / 1.5) / 10) * config.floatIntensity;
      material.uniforms.uTime.value += delta;
    }

    pointerSpeed *= Math.exp(-3 * delta);

    if (delta > 0) simulate(delta);
    renderer.render(scene, camera);
  });

  return {
    setOptions(next: ParticleObjectOptions) {
      const previousDistance = config.cameraDistance;
      const previousCount = config.count;
      Object.assign(config, next);
      if (config.cameraDistance !== previousDistance) {
        camera.position.copy(CAMERA_DIR).multiplyScalar(config.cameraDistance);
      }
      applyOptions();
      if (config.count !== previousCount) buildCloud();
      loadAsset();
    },
    resize,
    destroy() {
      disposed = true;
      loadToken += 1;
      renderer.setAnimationLoop(null);
      observer.disconnect();
      viewObserver?.disconnect();
      motionQuery.removeEventListener("change", onMotionChange);
      canvas.removeEventListener("pointerdown", onPointerMove);
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerup", onPointerLeave);
      canvas.removeEventListener("pointerleave", onPointerLeave);
      canvas.removeEventListener("pointercancel", onPointerLeave);
      controls.dispose();
      clearAsset();
      material.dispose();
      draco.dispose();
      renderer.dispose();
    },
  };
}

export interface ParticleObjectProps extends ParticleObjectOptions {
  className?: string;
  style?: React.CSSProperties;
  canvasTouchAction?: React.CSSProperties["touchAction"];
}

export function ParticleObject({
  className,
  style,
  canvasTouchAction = "none",
  ...options
}: ParticleObjectProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const instanceRef = useRef<ParticleObjectInstance | null>(null);
  const [initialOptions] = useState(options);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    instanceRef.current = createParticleObject({ canvas }, initialOptions);
    return () => {
      instanceRef.current?.destroy();
      instanceRef.current = null;
    };
  }, [initialOptions]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    // OrbitControls sets touch-action to none while it attaches its listeners.
    // Restore the embedding surface's policy after the controller is created.
    canvas.style.touchAction = canvasTouchAction;
  }, [canvasTouchAction]);

  useEffect(() => {
    instanceRef.current?.setOptions(options);
  });

  return (
    <div className={className} style={{ position: "relative", ...style }}>
      <canvas
        ref={canvasRef}
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          display: "block",
          touchAction: canvasTouchAction,
        }}
      />
    </div>
  );
}


export default ParticleObject;
