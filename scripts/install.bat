@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: ============================================================================
:: nanobot Windows Installer (PyPI Only) - Virtual Environment Only
:: ============================================================================
:: Installs nanobot in a dedicated virtual environment.
:: Automatically installs Python 3.14 if Python 3.11+ is not found.
::
:: Usage:
::   install.bat
::   install.bat --tuna
::
:: ============================================================================

:: Colors
set "RESET=[0m"
set "RED=[31m"
set "GREEN=[32m"
set "YELLOW=[33m"
set "CYAN=[36m"
set "BOLD=[1m"

:: Configuration
set "NANOBOT_HOME=%USERPROFILE%\.nanobot"
set "MIN_REQUIRED_VERSION=3.11"
set "INSTALL_VERSION=3.14"
set "TUNA_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"

:: Options
set "USE_TUNA_MIRROR=false"
set "FORCE_TUNA=false"

:: ============================================================================
:: Helper functions
:: ============================================================================

:print_color
    echo %~2
    exit /b 0

:log_info
    call :print_color "!CYAN!→ !RESET!%~1"
    exit /b 0

:log_success
    call :print_color "!GREEN!✓ !RESET!%~1"
    exit /b 0

:log_warn
    call :print_color "!YELLOW!⚠ !RESET!%~1"
    exit /b 0

:log_error
    call :print_color "!RED!✗ !RESET!%~1"
    exit /b 0

:print_banner
    echo.
    call :print_color "!CYAN!!BOLD!"
    echo ┌─────────────────────────────────────────────────────────┐
    echo │        🐈 nanobot Virtual Environment Installer        │
    echo ├─────────────────────────────────────────────────────────┤
    echo │   Installs in %NANOBOT_HOME%\venv                      │
    echo │   Python 3.11+ required                                │
    echo └─────────────────────────────────────────────────────────┘
    call :print_color "!RESET!"
    exit /b 0

:: Check if version >= required
:version_ge
    setlocal
    set "v1=%~1"
    set "v2=%~2"
    
    :: Simple version comparison for major.minor
    for /f "tokens=1,2 delims=." %%a in ("!v1!") do (
        set "major1=%%a"
        set "minor1=%%b"
    )
    for /f "tokens=1,2 delims=." %%a in ("!v2!") do (
        set "major2=%%a"
        set "minor2=%%b"
    )
    
    if !major1! gtr !major2! (
        exit /b 0
    ) else if !major1! equ !major2! (
        if !minor1! geq !minor2! (
            exit /b 0
        ) else (
            exit /b 1
        )
    ) else (
        exit /b 1
    )
    endlocal

:: ============================================================================
:: Python installation and management
:: ============================================================================

:install_python_314
    call :log_info "Installing Python %INSTALL_VERSION%..."
    
    :: Check if running as administrator
    net session >nul 2>&1
    if %errorLevel% neq 0 (
        call :log_error "Please run as administrator to install Python"
        echo.
        echo 1. Press Win+X, select "Windows PowerShell (Admin)"
        echo 2. Navigate to this script's directory
        echo 3. Run: .\install.bat
        pause
        exit /b 1
    )
    
    call :log_info "Downloading Python %INSTALL_VERSION% installer..."
    
    :: Download Python installer
    powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/%INSTALL_VERSION%.0/python-%INSTALL_VERSION%.0-amd64.exe' -OutFile '%TEMP%\python-%INSTALL_VERSION%.exe'"
    
    if not exist "%TEMP%\python-%INSTALL_VERSION%.exe" (
        call :log_error "Failed to download Python installer"
        exit /b 1
    )
    
    call :log_info "Installing Python %INSTALL_VERSION%..."
    
    :: Install Python with options
    "%TEMP%\python-%INSTALL_VERSION%.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
    
    :: Clean up installer
    del "%TEMP%\python-%INSTALL_VERSION%.exe"
    
    :: Verify installation
    python --version >nul 2>&1
    if %errorLevel% equ 0 (
        for /f "tokens=2" %%i in ('python --version 2^>nul') do set "version=%%i"
        call :log_success "Installed: Python !version!"
    ) else (
        call :log_error "Python installation may have failed"
        exit /b 1
    )
    
    exit /b 0

:check_and_install_python
    call :log_info "Checking Python version (requires 3.11+)..."
    
    :: Try to find Python
    set "python_cmd="
    set "found_version="
    
    :: Check python command
    python --version >nul 2>&1
    if %errorLevel% equ 0 (
        for /f "tokens=2" %%i in ('python --version 2^>nul') do set "found_version=%%i"
        set "python_cmd=python"
    ) else (
        :: Check python3 command
        python3 --version >nul 2>&1
        if %errorLevel% equ 0 (
            for /f "tokens=2" %%i in ('python3 --version 2^>nul') do set "found_version=%%i"
            set "python_cmd=python3"
        )
    )
    
    if defined python_cmd (
        :: Compare versions
        call :version_ge "%found_version%" "%MIN_REQUIRED_VERSION%"
        if %errorLevel% equ 0 (
            where python >nul
            if %errorLevel% equ 0 (
                for /f "delims=" %%i in ('where python') do set "PYTHON_PATH=%%i"
            )
            call :log_success "Found Python %found_version% (%python_cmd%)"
            exit /b 0
        ) else (
            call :log_error "Python %found_version% is too old (requires %MIN_REQUIRED_VERSION%+)"
        )
    ) else (
        call :log_error "No Python installation found"
    )
    
    :: Always install Python 3.14 automatically
    echo.
    call :log_info "Python %MIN_REQUIRED_VERSION%+ is required for nanobot"
    call :log_info "Installing Python %INSTALL_VERSION%..."
    
    call :install_python_314
    
    :: Set Python path after installation
    where python >nul
    if %errorLevel% equ 0 (
        for /f "delims=" %%i in ('where python') do set "PYTHON_PATH=%%i"
    ) else (
        call :log_error "Python not found after installation"
        exit /b 1
    )
    
    exit /b 0

:show_python_install_help
    echo.
    echo Please install Python %MIN_REQUIRED_VERSION% or higher manually:
    echo.
    echo 1. Download Python installer from:
    echo    https://www.python.org/downloads/
    echo.
    echo 2. During installation, make sure to check:
    echo    - [x] Add Python to PATH
    echo    - [x] Install pip
    echo.
    echo 3. After installation, re-run this script.
    echo.
    exit /b 0

:: ============================================================================
:: Detection functions
:: ============================================================================

:detect_china_region
    :: Simple detection for China region
    set "detected=false"
    
    :: Method 1: Check timezone
    for /f "tokens=3" %%i in ('tzutil /g') do (
        echo %%i | findstr /i "China" >nul
        if !errorlevel! equ 0 set "detected=true"
    )
    
    :: Method 2: Check system locale
    if "%detected%"=="false" (
        powershell -Command "[System.Globalization.RegionInfo]::CurrentRegion.TwoLetterISORegionName" | findstr /i "CN" >nul
        if !errorlevel! equ 0 set "detected=true"
    )
    
    echo %detected%
    exit /b 0

:: ============================================================================
:: Mirror configuration
:: ============================================================================

:configure_mirror
    if "%USE_TUNA_MIRROR%"=="true" (
        set "PIP_INDEX_URL=%TUNA_MIRROR%"
        set "PIP_EXTRA_INDEX_URL=https://pypi.org/simple"
        call :log_info "Using TUNA mirror: %TUNA_MIRROR%"
    )
    
    :: Respect user's environment variable
    if defined PIP_INDEX_URL (
        call :log_info "Using custom mirror: %PIP_INDEX_URL%"
    )
    exit /b 0

:: ============================================================================
:: Virtual environment installation
:: ============================================================================

:create_virtual_environment
    call :log_info "Creating virtual environment at %NANOBOT_HOME%\venv..."
    
    :: Remove existing venv if it exists
    if exist "%NANOBOT_HOME%\venv" (
        call :log_info "Removing existing virtual environment..."
        rmdir /s /q "%NANOBOT_HOME%\venv"
    )
    
    :: Create virtual environment
    "%PYTHON_PATH%" -m venv "%NANOBOT_HOME%\venv" 2>nul
    if %errorLevel% neq 0 (
        call :log_error "Failed to create virtual environment"
        echo Try: %PYTHON_PATH% -m ensurepip --upgrade
        exit /b 1
    )
    
    call :log_success "Virtual environment created"
    exit /b 0

:install_nanobot_in_venv
    call :log_info "Installing nanobot in virtual environment..."
    
    set "VIRTUAL_ENV=%NANOBOT_HOME%\venv"
    set "VENV_PYTHON=%VIRTUAL_ENV%\Scripts\python.exe"
    set "VENV_PIP=%VIRTUAL_ENV%\Scripts\pip.exe"
    
    :: Upgrade pip
    call :log_info "Upgrading pip..."
    "%VENV_PIP%" install --upgrade pip setuptools wheel >nul 2>&1
    
    :: Install nanobot
    if defined PIP_INDEX_URL (
        call :log_info "Installing with mirror..."
        "%VENV_PIP%" install nanobot --index-url "%PIP_INDEX_URL%" >nul 2>&1
    ) else (
        call :log_info "Installing from official PyPI..."
        "%VENV_PIP%" install nanobot >nul 2>&1
    )
    
    set "NANOBOT_BIN=%VIRTUAL_ENV%\Scripts\nanobot.exe"
    
    :: Verify installation
    if exist "%NANOBOT_BIN%" (
        for /f "tokens=*" %%i in ('"%NANOBOT_BIN%" --version 2^>nul') do set "version=%%i"
        if not defined version set "version=unknown"
        call :log_success "nanobot %version% installed"
    ) else (
        call :log_error "nanobot installation failed"
        exit /b 1
    )
    exit /b 0

:create_command_symlink
    call :log_info "Creating command shortcut..."
    
    :: Create desktop shortcut
    set "LINK_DIR=%USERPROFILE%\Desktop"
    
    if exist "%NANOBOT_BIN%" (
        :: Create shortcut to Python executable
        powershell -Command "
            $WshShell = New-Object -ComObject WScript.Shell;
            $Shortcut = $WshShell.CreateShortcut('%LINK_DIR%\nanobot.lnk');
            $Shortcut.TargetPath = '%NANOBOT_BIN%';
            $Shortcut.WorkingDirectory = '%NANOBOT_HOME%';
            $Shortcut.Save()
        "
        
        call :log_success "Shortcut created: %LINK_DIR%\nanobot.lnk"
        
        :: Check if Python Scripts is in PATH
        echo %PATH% | findstr /i "Scripts" >nul
        if %errorLevel% neq 0 (
            echo.
            call :log_warn "Add Python Scripts to PATH for command line usage:"
            echo setx PATH "%%PATH%%;%USERPROFILE%\AppData\Local\Programs\Python\Python314\Scripts"
        )
    )
    exit /b 0

:: ============================================================================
:: Main function
:: ============================================================================

:main
    call :print_banner
    
    :: Parse arguments
    for %%a in (%*) do (
        if "%%a"=="--tuna" (
            set "USE_TUNA_MIRROR=true"
            set "FORCE_TUNA=true"
        )
        if "%%a"=="-h" (
            call :show_help
            exit /b 0
        )
        if "%%a"=="--help" (
            call :show_help
            exit /b 0
        )
    )
    
    :: Step 1: Check and install Python first
    call :check_and_install_python
    if %errorLevel% neq 0 exit /b 1
    
    :: Step 2: Detect China region AFTER Python is installed
    if "%FORCE_TUNA%"=="false" (
        call :detect_china_region
        if "!errorlevel!"=="0" (
            set "USE_TUNA_MIRROR=true"
            call :log_info "China region detected, using TUNA mirror"
        )
    )
    
    :: Step 3: Configure PyPI mirror
    call :configure_mirror
    
    :: Step 4: Install nanobot in virtual environment
    call :create_virtual_environment
    if %errorLevel% neq 0 exit /b 1
    
    call :install_nanobot_in_venv
    if %errorLevel% neq 0 exit /b 1
    
    call :create_command_symlink
    
    call :show_success_message
    
    pause
    exit /b 0

:show_help
    echo nanobot Virtual Environment Installer
    echo.
    echo Usage:
    echo   install.bat [OPTIONS]
    echo.
    echo Options:
    echo   --tuna        Use TUNA mirror (pypi.tuna.tsinghua.edu.cn)
    echo   -h, --help    Show this help message
    echo.
    echo Environment Variables:
    echo   PIP_INDEX_URL Custom PyPI mirror URL
    echo   NANOBOT_HOME  Data directory (default: %%USERPROFILE%%\.nanobot)
    echo.
    echo Examples:
    echo   install.bat --tuna
    echo   set PIP_INDEX_URL=https://mirror.example.com/simple ^&^& install.bat
    exit /b 0

:show_success_message
    echo.
    call :print_color "!GREEN!!BOLD!"
    echo ┌─────────────────────────────────────────────────────────┐
    echo │    ✓ nanobot Installation Complete!                     │
    echo └─────────────────────────────────────────────────────────┘
    call :print_color "!RESET!"
    echo.
    call :print_color "!CYAN!📁 Installation Summary:!RESET!"
    echo   Virtual Environment: %NANOBOT_HOME%\venv\
    echo   nanobot Command:     %NANOBOT_HOME%\venv\Scripts\nanobot.exe
    echo   Desktop Shortcut:    %USERPROFILE%\Desktop\nanobot.lnk
    echo.
    
    call :print_color "!CYAN!🚀 Next Steps:!RESET!"
    echo   1. Configure nanobot:
    echo      Open Command Prompt as administrator and run:
    echo      %NANOBOT_HOME%\venv\Scripts\nanobot onboard
    echo.
    echo   2. Start using nanobot:
    echo      %NANOBOT_HOME%\venv\Scripts\nanobot
    echo      %NANOBOT_HOME%\venv\Scripts\nanobot gateway
    echo.
    
    call :print_color "!CYAN!🔧 Virtual Environment Management:!RESET!"
    echo   To activate the virtual environment:
    echo   %NANOBOT_HOME%\venv\Scripts\activate
    echo.
    echo   To deactivate:
    echo   deactivate
    echo.
    
    call :print_color "!YELLOW!⚠  For Command Line Usage:!RESET!"
    echo   Add Python Scripts to your PATH:
    echo   setx PATH "%%PATH%%;%USERPROFILE%\AppData\Local\Programs\Python\Python314\Scripts"
    echo.
    
    call :print_color "!CYAN!💡 Quick Test:!RESET!"
    echo   %NANOBOT_HOME%\venv\Scripts\nanobot --version
    echo.
    exit /b 0

:: ============================================================================
:: Start execution
:: ============================================================================

:: Enable delayed expansion for variables
setlocal enabledelayedexpansion

:: Enable ANSI color support in Windows 10+
if not defined PWD (
    reg add "HKCU\Console" /v VirtualTerminalLevel /t REG_DWORD /d 1 /f >nul 2>&1
)

:: Execute main function
call :main %*

endlocal
