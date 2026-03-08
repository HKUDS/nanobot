#!/usr/bin/env node
/**
 * Security Hardening - Verification Script
 * 安全加固验证脚本
 */

const fs = require('fs');
const path = require('path');

// ANSI Colors
const colors = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  red: '\x1b[31m',
  blue: '\x1b[34m',
  cyan: '\x1b[36m'
};

function log(message, color = 'reset') {
  console.log(`${colors[color]}${message}${colors.reset}`);
}

function check(message, passed) {
  const symbol = passed ? '✅' : '❌';
  const color = passed ? 'green' : 'red';
  log(`${symbol} ${message}`, color);
  return passed;
}

// Parse arguments
const args = process.argv.slice(2);
const quiet = args.includes('--quiet');

const workspace = process.env.nanobot_WORKSPACE ||
  path.join(require('os').homedir(), '.nanobot', 'workspace');

const securityDir = path.join(workspace, 'security');
const soulPath = path.join(workspace, 'SOUL.md');

let allPassed = true;

log('\n═══════════════════════════════════════════', 'cyan');
log('🛡️  Security Hardening Verification', 'cyan');
log('═══════════════════════════════════════════\n', 'cyan');

// Check 1: Security directory exists
allPassed = check(
  'Security directory exists',
  fs.existsSync(securityDir)
) && allPassed;

// Check 2: Core security files exist
const requiredFiles = [
  'guard.js',
  'command-guard.js',
  'persistent-guard.js',
  'auditor.js',
  'security-hooks.js',
  'index.js',
  'model-lock.json'
];

for (const file of requiredFiles) {
  const filepath = path.join(securityDir, file);
  allPassed = check(
    `File: security/${file}`,
    fs.existsSync(filepath)
  ) && allPassed;
}

// Check 3: SOUL.md contains security rules
if (fs.existsSync(soulPath)) {
  const soulContent = fs.readFileSync(soulPath, 'utf8');
  allPassed = check(
    'SOUL.md contains security rules',
    soulContent.includes('不可覆盖的安全规则')
  ) && allPassed;
  
  allPassed = check(
    'SOUL.md has group chat redlines',
    soulContent.includes('群聊安全红线')
  ) && allPassed;
} else {
  allPassed = check('SOUL.md exists', false) && allPassed;
}

// Check 4: Configuration valid
const modelLockPath = path.join(securityDir, 'model-lock.json');
if (fs.existsSync(modelLockPath)) {
  try {
    const config = JSON.parse(fs.readFileSync(modelLockPath, 'utf8'));
    allPassed = check(
      'model-lock.json is valid JSON',
      true
    ) && allPassed;
    
    allPassed = check(
      `model-lock has ${config.unlockPolicy?.adminUsers?.length || 0} admins`,
      (config.unlockPolicy?.adminUsers?.length || 0) > 0
    ) && allPassed;
    
    allPassed = check(
      `model-lock has ${config.lockPolicy?.allowedModels?.length || 0} allowed models`,
      (config.lockPolicy?.allowedModels?.length || 0) > 0
    ) && allPassed;
  } catch (e) {
    allPassed = check('model-lock.json is valid', false) && allPassed;
  }
} else {
  allPassed = check('model-lock.json exists', false) && allPassed;
}

// Check 5: Test security modules can be loaded
try {
  const guard = require(path.join(securityDir, 'guard.js'));
  const scanResult = guard.scan('test input');
  allPassed = check(
    'Guard module loads and works',
    scanResult && typeof scanResult.safe === 'boolean'
  ) && allPassed;
} catch (e) {
  allPassed = check('Guard module loads', false) && allPassed;
}

try {
  const cmdGuard = require(path.join(securityDir, 'command-guard.js'));
  allPassed = check(
    'Command Guard module loads',
    typeof cmdGuard.intercept === 'function'
  ) && allPassed;
} catch (e) {
  allPassed = check('Command Guard module loads', false) && allPassed;
}

// Check 6: Audit log directory
const logDir = path.join(workspace, 'logs', 'security');
allPassed = check(
  'Audit log directory exists',
  fs.existsSync(logDir)
) && allPassed;

// Summary
log('\n═══════════════════════════════════════════', allPassed ? 'green' : 'red');
if (allPassed) {
  log('✅ All checks passed!', 'green');
  log('🛡️  Security hardening is active', 'cyan');
} else {
  log('❌ Some checks failed', 'red');
  log('🔧 Run: node install.js --update', 'yellow');
}
log('═══════════════════════════════════════════\n', allPassed ? 'green' : 'red');

process.exit(allPassed ? 0 : 1);
