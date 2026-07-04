from pathlib import Path
content = '''import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';

const AGENTS = [
  { id: 'nova', name: 'Nova', specialty: 'Insight synthesis', color: '#be88ff', panel: 'top-left' },
  { id: 'pulse', name: 'Pulse', specialty: 'Flow & ops', color: '#4ff6d5', panel: 'top-right' },
  { id: 'forge', name: 'Forge', specialty: 'Execution tools', color: '#7fd7ff', panel: 'bottom-left' },
];

const MOODS = {
  idle: { color: '#8c95ff', speed: 0.08, noise: 0.16, halo: 0.24, glow: 0.28, ring: 0.08 },
  listening: { color: '#ffb96f', speed: 0.18, noise: 0.22, halo: 0.72, glow: 0.7, ring: 0.18 },
  processing: { color: '#75ffd0', speed: 0.42, noise: 0.46, halo: 0.48, glow: 0.64, ring: 1.0 },
  speaking: { color: '#9ff8ff', speed: 0.66, noise: 0.88, halo: 0.94, glow: 0.9, ring: 0.38 },
  error: { color: '#ff5a67', speed: 0.06, noise: 0.08, halo: 0.18, glow: 0.24, ring: 0.05 },
};

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function easeColor(current, target, ease) {
  return {
    r: lerp(current.r, target.r, ease),
    g: lerp(current.g, target.g, ease),
    b: lerp(current.b, target.b, ease),
  };
}

function hexToRgb(hex) {
  const cleaned = hex.replace('#', '');
  const integer = parseInt(cleaned, 16);
  return {
    r: ((integer >> 16) & 255) / 255,
    g: ((integer >> 8) & 255) / 255,
    b: (integer & 255) / 255,
  };
}

function createAgentIcon(color, initials) {
  const size = 144;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');

  const gradient = ctx.createRadialGradient(size * 0.45, size * 0.38, size * 0.03, size * 0.5, size * 0.5, size * 0.5);
  gradient.addColorStop(0, 'rgba(255,255,255,0.95)');
  gradient.addColorStop(0.25, `${color}cc`);
  gradient.addColorStop(1, 'rgba(0,0,0,0.04)');

  ctx.fillStyle = '#07101e';
  ctx.fillRect(0, 0, size, size);
  ctx.fillStyle = gradient;
  ctx.beginPath();
  ctx.arc(size / 2, size / 2, size * 0.42, 0, Math.PI * 2);
  ctx.fill();

  ctx.strokeStyle = color;
  ctx.lineWidth = 6;
  ctx.beginPath();
  ctx.arc(size / 2, size / 2, size * 0.44, 0, Math.PI * 2);
  ctx.stroke();

  ctx.fillStyle = '#eefcff';
  ctx.font = 'bold 58px Inter, system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(initials, size / 2, size / 2 + 2);

  return canvas;
}

function mapAgentPanel(panel) {
  switch (panel) {
    case 'top-left':
      return { x: 0.12, y: 0.14, label: 'Insight' };
    case 'top-right':
      return { x: 0.88, y: 0.15, label: 'Flow' };
    case 'bottom-left':
      return { x: 0.14, y: 0.82, label: 'Execute' };
    default:
      return { x: 0.5, y: 0.82, label: 'Agent' };
  }
}

function projectToScreen(position, camera, width, height) {
  const projected = position.clone().project(camera);
  return {
    x: (projected.x * 0.5 + 0.5) * width,
    y: (-projected.y * 0.5 + 0.5) * height,
    depth: projected.z,
  };
}

export default function CosmicScene() {
  const bgCanvasRef = useRef(null);
  const orbCanvasRef = useRef(null);
  const labelRefs = useRef(new Map());
  const [state, setState] = useState('idle');
  const [performanceMode, setPerformanceMode] = useState(false);
  const [microphoneEnabled, setMicrophoneEnabled] = useState(false);
  const [workingAgentId, setWorkingAgentId] = useState(null);

  const [agents] = useState(
    AGENTS.map((agent, index) => ({
      ...agent,
      angle: (Math.PI * 2 * index) / AGENTS.length,
      orbitRadius: 1.75 + index * 0.24,
      tilt: (index % 2 ? -1 : 1) * (0.28 + index * 0.06),
      speed: 0.16 + index * 0.03,
      phase: Math.random() * Math.PI * 2,
    })),
  );

  useEffect(() => {
    const bgCanvas = bgCanvasRef.current;
    const orbCanvas = orbCanvasRef.current;
    if (!bgCanvas || !orbCanvas) return;

    const viewport = { width: window.innerWidth, height: window.innerHeight };
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 1.8);

    const bgRenderer = new THREE.WebGLRenderer({ canvas: bgCanvas, alpha: true, antialias: false, powerPreference: 'low-power' });
    const orbRenderer = new THREE.WebGLRenderer({ canvas: orbCanvas, alpha: true, antialias: true, powerPreference: 'high-performance' });
    bgRenderer.setPixelRatio(pixelRatio);
    orbRenderer.setPixelRatio(pixelRatio);

    const bgScene = new THREE.Scene();
    const orbScene = new THREE.Scene();
    const bgCamera = new THREE.PerspectiveCamera(34, viewport.width / viewport.height, 0.1, 25);
    const orbCamera = new THREE.PerspectiveCamera(34, viewport.width / viewport.height, 0.1, 25);
    bgCamera.position.set(0, 0, 5.8);
    orbCamera.position.set(0, 0, 5.8);

    const nebulaMaterial = new THREE.ShaderMaterial({
      uniforms: {
        time: { value: 0 },
        resolution: { value: new THREE.Vector2(viewport.width, viewport.height) },
      },
      vertexShader: `varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }`,
      fragmentShader: `uniform float time; uniform vec2 resolution; varying vec2 vUv;
        float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7)))*43758.5453123); }
        float noise(vec2 p){ vec2 i=floor(p); vec2 f=fract(p); float a=hash(i); float b=hash(i+vec2(1.0,0.0)); float c=hash(i+vec2(0.0,1.0)); float d=hash(i+vec2(1.0,1.0)); vec2 u=f*f*(3.0-2.0*f); return mix(a,b,u.x) + (c-a)*u.y*(1.0-u.x) + (d-b)*u.x*u.y; }
        void main(){ vec2 uv=(vUv-0.5)*vec2(resolution.x/resolution.y,1.0); float t=time*0.12; float clouds=0.0; clouds += noise(uv*0.95 + vec2(t,t*1.3))*0.48; clouds += noise(uv*1.75 - vec2(t*0.86,t*1.08))*0.33; clouds += noise(uv*3.3 + vec2(-t*0.4,t*0.22))*0.2; float nebula = smoothstep(0.18, 0.46, length(uv)*0.92 + clouds*0.52); vec3 base = mix(vec3(0.017,0.028,0.08), vec3(0.22,0.38,0.9), nebula); vec3 glow = mix(vec3(0.16,0.96,0.78), vec3(0.82,0.42,1.0), smoothstep(0.24,0.78, clouds)); float stars = pow(smoothstep(0.987,0.92, fract(sin(dot(uv*108.0 + t*0.2, vec2(12.9898,78.233)))*43758.5453)), 10.0); gl_FragColor = vec4(base + glow*0.34 + exp(-length(uv)*2.1)*0.2 + stars*0.24, 1.0); }`,
      transparent: false,
      depthWrite: false,
    });

    const bgPlane = new THREE.Mesh(new THREE.PlaneGeometry(14, 8.8), nebulaMaterial);
    bgPlane.position.z = -9.2;
    bgScene.add(bgPlane);

    const starCount = window.innerWidth < 700 ? 380 : 900;
    const starGeo = new THREE.BufferGeometry();
    const starPositions = new Float32Array(starCount * 3);
    for (let i = 0; i < starCount; i += 1) {
      starPositions[i * 3 + 0] = (Math.random() - 0.5) * 14;
      starPositions[i * 3 + 1] = (Math.random() - 0.5) * 9;
      starPositions[i * 3 + 2] = -7 - Math.random() * 7;
    }
    starGeo.setAttribute('position', new THREE.BufferAttribute(starPositions, 3));
    const stars = new THREE.Points(starGeo, new THREE.PointsMaterial({ color: 0xffffff, size: 1.4, transparent: true, opacity: 0.55, depthWrite: false }));
    bgScene.add(stars);

    const networkGroup = new THREE.Group();
    const nodePositions = [];
    for (let ci = 0; ci < 8; ci += 1) {
      const root = new THREE.Vector3((Math.random() - 0.5) * 6, (Math.random() - 0.5) * 4, -10 - Math.random() * 5);
      for (let ni = 0; ni < 8; ni += 1) {
        const offset = new THREE.Vector3((Math.random() - 0.5) * 0.75, (Math.random() - 0.5) * 0.75, (Math.random() - 0.5) * 0.75);
        nodePositions.push(root.clone().add(offset));
      }
    }
    const nodeArray = new Float32Array(nodePositions.length * 3);
    nodePositions.forEach((point, idx) => {
      nodeArray[idx * 3 + 0] = point.x;
      nodeArray[idx * 3 + 1] = point.y;
      nodeArray[idx * 3 + 2] = point.z;
    });
    const nodeGeo = new THREE.BufferGeometry();
    nodeGeo.setAttribute('position', new THREE.BufferAttribute(nodeArray, 3));
    networkGroup.add(new THREE.Points(nodeGeo, new THREE.PointsMaterial({ color: 0xa3c9ff, size: 2.1, transparent: true, opacity: 0.32, depthWrite: false })));

    const edgeArray = [];
    for (let i = 0; i < nodePositions.length; i += 1) {
      for (let j = i + 1; j < nodePositions.length; j += 1) {
        if (nodePositions[i].distanceTo(nodePositions[j]) < 2.3) {
          edgeArray.push(nodePositions[i].x, nodePositions[i].y, nodePositions[i].z);
          edgeArray.push(nodePositions[j].x, nodePositions[j].y, nodePositions[j].z);
        }
      }
    }
    const edgeGeo = new THREE.BufferGeometry();
    edgeGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(edgeArray), 3));
    networkGroup.add(new THREE.LineSegments(edgeGeo, new THREE.LineBasicMaterial({ color: 0x94c9ff, transparent: true, opacity: 0.18, depthWrite: false })));
    networkGroup.rotation.set(0.16, 0.2, 0);
    bgScene.add(networkGroup);

    const orbGroup = new THREE.Group();
    orbScene.add(orbGroup);

    const orbGeometry = new THREE.IcosahedronGeometry(1, 4);
    const basePositions = Float32Array.from(orbGeometry.attributes.position.array);
    const orbMaterial = new THREE.MeshBasicMaterial({ color: new THREE.Color(MOODS.idle.color), wireframe: true, transparent: true, opacity: 0.7, toneMapped: false });
    const orbMesh = new THREE.Mesh(orbGeometry, orbMaterial);
    orbGroup.add(orbMesh);

    const haloMaterial = new THREE.ShaderMaterial({
      uniforms: { color: { value: new THREE.Color(MOODS.idle.color) }, intensity: { value: 0.16 } },
      vertexShader: 'varying vec3 vNormal; void main(){ vNormal=normal; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }',
      fragmentShader: 'uniform vec3 color; uniform float intensity; varying vec3 vNormal; void main(){ float glow = pow(1.0 - abs(dot(normalize(vNormal), vec3(0,0,1))), 2.2); gl_FragColor = vec4(color * 1.1, glow * intensity); }',
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const haloMesh = new THREE.Mesh(new THREE.IcosahedronGeometry(1.18, 3), haloMaterial);
    orbGroup.add(haloMesh);

    const ringGroup = new THREE.Group();
    function makeRing(radius, opacity) {
      const pts = [];
      const segments = 96;
      for (let i = 0; i <= segments; i += 1) {
        const angle = (i / segments) * Math.PI * 2;
        pts.push(new THREE.Vector3(Math.cos(angle) * radius, Math.sin(angle) * radius * 0.04, Math.sin(angle) * radius * 0.06));
      }
      return new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: 0x8fcfff, transparent: true, opacity, toneMapped: false }));
    }
    for (let i = 0; i < 4; i += 1) {
      const ring = makeRing(1.24 + i * 0.14, 0.08 + i * 0.06);
      ring.rotation.x = Math.PI * 0.5;
      ring.rotation.z = i * 0.42;
      ringGroup.add(ring);
    }
    orbGroup.add(ringGroup);

    const agentSprites = agents.map((agent) => {
      const initials = agent.name.split(' ').map((part) => part[0]).slice(0, 2).join('').toUpperCase();
      const texture = new THREE.CanvasTexture(createAgentIcon(agent.color, initials));
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, opacity: 0.92, depthWrite: false, blending: THREE.AdditiveBlending }));
      sprite.scale.set(0.34, 0.34, 0.34);
      orbGroup.add(sprite);
      return { ...agent, sprite, orbitAngle: agent.angle };
    });

    const beamGeometry = new THREE.BufferGeometry();
    beamGeometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
    const beamLine = new THREE.Line(beamGeometry, new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0, toneMapped: false }));
    orbScene.add(beamLine);

    const moodTarget = { ...hexToRgb(MOODS.idle.color), speed: MOODS.idle.speed, noise: MOODS.idle.noise, halo: MOODS.idle.halo, glow: MOODS.idle.glow, ring: MOODS.idle.ring };
    const moodCurrent = { ...moodTarget };
    let lastTime = 0;
    let elapsed = 0;

    function resize() {
      viewport.width = window.innerWidth;
      viewport.height = window.innerHeight;
      bgRenderer.setSize(viewport.width, viewport.height, false);
      orbRenderer.setSize(viewport.width, viewport.height, false);
      bgCamera.aspect = viewport.width / viewport.height;
      orbCamera.aspect = viewport.width / viewport.height;
      bgCamera.updateProjectionMatrix();
      orbCamera.updateProjectionMatrix();
      nebulaMaterial.uniforms.resolution.value.set(viewport.width, viewport.height);
    }

    function updateLabels() {
      agentSprites.forEach((agent) => {
        const label = labelRefs.current.get(agent.id);
        if (!label) return;
        const screen = projectToScreen(agent.sprite.position, orbCamera, viewport.width, viewport.height);
        const visible = screen.depth < 0.75 && screen.x > 0 && screen.x < viewport.width && screen.y > 0 && screen.y < viewport.height;
        label.style.opacity = visible ? `${clamp(1.2 - screen.depth, 0, 1)}` : '0';
        label.style.transform = `translate3d(${screen.x}px, ${screen.y}px, 0)`;
        label.style.zIndex = `${Math.round((1 - screen.depth) * 1000)}`;
      });
    }

    function updateMood(nextState) {
      const mood = MOODS[nextState] || MOODS.idle;
      moodTarget.color = hexToRgb(mood.color);
      moodTarget.speed = mood.speed;
      moodTarget.noise = mood.noise;
      moodTarget.halo = mood.halo;
      moodTarget.glow = mood.glow;
      moodTarget.ring = mood.ring;
    }

    function dispatchAgent(id) {
      const target = agentSprites.find((item) => item.id === id);
      if (!target) return;
      const p = target.sprite.position;
      const positions = beamLine.geometry.attributes.position.array;
      positions[0] = 0;
      positions[1] = 0;
      positions[2] = 0;
      positions[3] = p.x;
      positions[4] = p.y;
      positions[5] = p.z;
      beamLine.geometry.attributes.position.needsUpdate = true;
      beamLine.material.color.set(target.color);
      beamLine.material.opacity = 0.96;
      window.setTimeout(() => {
        beamLine.material.opacity = 0;
      }, 1400);
    }

    window.AvaScene = {
      setState: (nextState) => {
        setState(nextState);
        updateMood(nextState);
      },
      dispatchAgent,
      startWorking: (id) => setWorkingAgentId(id),
      stopWorking: () => setWorkingAgentId(null),
      setPerformance: (value) => setPerformanceMode(value),
    };

    function animate(time) {
      const seconds = time * 0.001;
      const delta = lastTime ? clamp(seconds - lastTime, 0, 0.06) : 0.016;
      lastTime = seconds;
      elapsed += delta;

      moodCurrent.color = easeColor(moodCurrent.color, moodTarget.color, 0.08);
      moodCurrent.speed = lerp(moodCurrent.speed, moodTarget.speed, 0.06);
      moodCurrent.noise = lerp(moodCurrent.noise, moodTarget.noise, 0.05);
      moodCurrent.halo = lerp(moodCurrent.halo, moodTarget.halo, 0.06);
      moodCurrent.glow = lerp(moodCurrent.glow, moodTarget.glow, 0.05);
      moodCurrent.ring = lerp(moodCurrent.ring, moodTarget.ring, 0.04);

      const color = new THREE.Color(moodCurrent.color.r, moodCurrent.color.g, moodCurrent.color.b);
      orbMaterial.color.copy(color);
      haloMaterial.uniforms.color.value.copy(color);
      haloMaterial.uniforms.intensity.value = moodCurrent.halo * 0.16 + 0.04;

      const scale = 1 + Math.sin(elapsed * 1.8) * 0.02 + moodCurrent.glow * 0.05;
      orbGroup.scale.setScalar(scale);
      orbGroup.rotation.y += (moodCurrent.speed * 0.34 + 0.01) * delta;
      orbGroup.rotation.x += (moodCurrent.speed * 0.09 + 0.007) * delta;

      const posAttr = orbGeometry.attributes.position;
      for (let i = 0; i < posAttr.count; i += 1) {
        const ix = i * 3;
        const ox = basePositions[ix];
        const oy = basePositions[ix + 1];
        const oz = basePositions[ix + 2];
        const noise = Math.sin((ox + oy + oz) * 1.9 + elapsed * 1.8) * 0.08 + Math.cos((oy - oz + ox) * 2.3 + elapsed * 2.4) * 0.06;
        const radius = 1 + noise * (moodCurrent.noise + 0.06);
        posAttr.array[ix] = ox * radius;
        posAttr.array[ix + 1] = oy * radius;
        posAttr.array[ix + 2] = oz * radius;
      }
      posAttr.needsUpdate = true;
      orbGeometry.computeVertexNormals();

      ringGroup.children.forEach((ring, idx) => {
        ring.rotation.y += 0.08 + idx * 0.03 + moodCurrent.ring * 0.04;
        ring.material.opacity = clamp(0.1 + moodCurrent.ring * 0.18 - idx * 0.03, 0.02, 0.42);
      });

      agentSprites.forEach((agent) => {
        agent.orbitAngle += (agent.speed + moodCurrent.speed * 0.12) * delta * (Math.sign(agent.tilt) || 1);
        const orbit = agent.orbitAngle + agent.phase;
        const x = Math.cos(orbit) * agent.orbitRadius;
        const y = Math.sin(orbit) * agent.orbitRadius * 0.18;
        const z = Math.sin(orbit * 0.92) * agent.orbitRadius * 0.33;
        const targetPos = new THREE.Vector3(x, y, z).applyAxisAngle(new THREE.Vector3(0, 0, 1), agent.tilt);
        if (workingAgentId === agent.id) {
          const panel = mapAgentPanel(agent.panel);
          const dock = new THREE.Vector3((panel.x - 0.5) * 5.0, (0.5 - panel.y) * 3.5, -0.16);
          agent.sprite.position.lerp(dock, 0.12);
          agent.sprite.scale.setScalar(0.36);
        } else {
          agent.sprite.position.lerp(targetPos, 0.14);
          agent.sprite.scale.setScalar(0.32 + Math.sin(elapsed * 2 + agent.phase) * 0.015);
        }
      });

      if (beamLine.material.opacity > 0) {
        beamLine.material.opacity = lerp(beamLine.material.opacity, 0, 0.04);
      }

      if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        bgScene.rotation.y += delta * 0.007;
        networkGroup.rotation.y += delta * 0.012;
      }

      nebulaMaterial.uniforms.time.value = elapsed;
      orbRenderer.render(orbScene, orbCamera);
      if (!performanceMode || Math.round(elapsed * 60) % 2 === 0) {
        bgRenderer.render(bgScene, bgCamera);
      }
      updateLabels();
      requestAnimationFrame(animate);
    }

    window.addEventListener('resize', resize);
    resize();
    requestAnimationFrame(animate);

    return () => {
      window.removeEventListener('resize', resize);
      bgRenderer.dispose();
      orbRenderer.dispose();
      window.AvaScene = undefined;
    };
  }, [performanceMode, workingAgentId]);

  return (
    <div className="cosmic-shell">
      <canvas ref={bgCanvasRef} className="scene-canvas" />
      <canvas ref={orbCanvasRef} className="scene-canvas" />
      <div className="scene-label-layer">
        <div className="scene-header">
          <div>
            <div className="scene-title">Ava</div>
            <div className="scene-subtitle">A living cosmic interface for your AI command field.</div>
          </div>
          <div className="scene-state-pill">{state.toUpperCase()}</div>
        </div>

        <div className="panel-grid">
          {agents.map((agent) => {
            const panel = mapAgentPanel(agent.panel);
            return (
              <div key={agent.id} className="panel-card" style={{ borderColor: agent.color }}>
                <div className="panel-title">{panel.label}</div>
                <div className="panel-subtitle">{agent.name}</div>
                <div className="panel-detail">{agent.specialty}</div>
              </div>
            );
          })}
        </div>

        {agents.map((agent) => (
          <div key={agent.id} className="agent-label" ref={(el) => el && labelRefs.current.set(agent.id, el)}>
            <div className="agent-label-name">{agent.name}</div>
            <div className="agent-label-role">{agent.specialty}</div>
          </div>
        ))}

        <div className="scene-controls">
          {['idle', 'listening', 'processing', 'speaking', 'error'].map((mode) => (
            <button type="button" className="control-pill" onClick={() => { setState(mode); if (window.AvaScene?.setState) window.AvaScene.setState(mode); }}>
              {mode}
            </button>
          ))}
          <button type="button" className="control-pill mini" onClick={() => window.AvaScene?.dispatchAgent(agents[0].id)}>
            Dispatch {agents[0].name}
          </button>
          <button type="button" className="control-pill mini" onClick={() => setWorkingAgentId((prev) => (prev ? null : agents[1].id))}>
            {workingAgentId ? 'Undock Pulse' : 'Work Pulse'}
          </button>
          <button type="button" className="control-pill accent" onClick={() => setMicrophoneEnabled(true)}>
            {microphoneEnabled ? 'Mic enabled' : 'Enable mic'}
          </button>
          <button type="button" className="control-pill mini" onClick={() => setPerformanceMode((prev) => !prev)}>
            Perf {performanceMode ? 'Low' : 'High'}
          </button>
        </div>
      </div>
    </div>
  );
}
'''
Path('src/cosmicScene.jsx').write_text(content, encoding='utf-8')
print('written')
