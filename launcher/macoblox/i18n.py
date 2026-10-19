"""Interface strings. English is the source language; set_language("ru")
switches to Russian."""

LANGUAGES = {"en": "English", "ru": "Русский"}

_language = "en"

RU = {
    "VR headset": "VR-шлем",
    "Experimental. Plays in Roblox's own VR mode on a headset connected through an OpenXR runtime such as WiVRn (Meta Quest) or Monado. Applies on next launch.":
        "Экспериментально. Запускает собственный VR-режим Roblox на шлеме, подключённом через среду OpenXR, например WiVRn (Meta Quest) или Monado. Применяется при следующем запуске.",
    "VR headset (OpenXR)": "VR-шлем (OpenXR)",
    "VR render resolution": "Разрешение рендеринга VR",
    "Percent of the headset's recommended size per eye. Lower is smoother.":
        "Процент от рекомендуемого шлемом размера на каждый глаз. Меньше — плавнее.",
    "Show the headset view in the game window": "Показывать изображение шлема в окне игры",
    "Both eyes side by side on the desktop. Off saves a little time per frame.":
        "Оба глаза рядом на рабочем столе. Если выключить, каждый кадр будет чуть быстрее.",
    "The OpenXR loader is not installed (package openxr or libopenxr-loader1).":
        "Загрузчик OpenXR не установлен (пакет openxr или libopenxr-loader1).",
    "No OpenXR runtime found. Install and start WiVRn or Monado.":
        "Среда OpenXR не найдена. Установите и запустите WiVRn или Monado.",
    "Uses {runtime}. Start it and connect the headset before playing.":
        "Используется {runtime}. Запустите её и подключите шлем перед игрой.",
    "Roblox update broke game compatibility": "Обновление Roblox нарушило совместимость с играми",
    "Roblox is no longer using RakNet. The latest Roblox update has broken game connection compatibility with Quadra. Games might not work or may show Error 256.\n\nCheck for a Quadra update. If a fix is not available yet, wait for a Quadra compatibility patch.":
        "Roblox больше не использует RakNet. Последнее обновление Roblox нарушило совместимость игровых подключений с Quadra. Игры могут не работать или выдавать ошибку 256.\n\nПроверьте обновления Quadra. Если исправление ещё не доступно, дождитесь патча совместимости для Quadra.",
    "View log": "Посмотреть журнал",
    "Check for CiderDarling updates": "Проверить обновления CiderDarling",
    "Check for CiderDarling updates automatically": "Автоматически проверять обновления CiderDarling",
    "Checks in the background. Install an available update in a separate terminal.":
        "Проверка в фоне. Установка доступного обновления в отдельном терминале.",
    "A CiderDarling update is available in Settings → CiderDarling.":
        "Обновление CiderDarling доступно в разделе «Настройки → CiderDarling».",
    "Could not check CiderDarling updates: {error}": "Не удалось проверить обновления CiderDarling: {error}",
    "No CiderDarling update is available.": "Обновлений CiderDarling нет.",
    "Installed {installed}, update {pinned} is available. Opens a separate terminal for installation.":
        "Установлена {installed}, доступно обновление {pinned}. Установка в отдельном терминале.",
    "{installed}; update {pinned} available": "{installed}; доступно обновление {pinned}",
    "Install CiderDarling": "Установить CiderDarling",
    "Install in terminal": "Установить в терминале",
    "Opens a separate terminal for the build and sudo prompts.": "Откроет отдельный терминал для сборки и запросов sudo.",
    "Installing CiderDarling in another terminal…": "CiderDarling устанавливается в другом терминале…",
    "Installing in a separate terminal. Your current runtime remains selected.":
        "Установка выполняется в отдельном терминале. Текущая среда остаётся выбранной.",
    "Install CiderDarling in a separate terminal, then apply the switch.":
        "Установите CiderDarling в отдельном терминале, затем примените переключение.",
    "Could not open an installation terminal.": "Не удалось открыть терминал для установки.",
    "No terminal application was found. Install one (for example xterm), or set the TERMINAL environment variable to your terminal's command, then try again.":
        "Не найден эмулятор терминала. Установите его (например, xterm) или укажите команду своего терминала в переменной окружения TERMINAL, затем повторите попытку.",
    "Could not install CiderDarling": "Не удалось установить CiderDarling",
    "Installation failed or was cancelled. See the separate terminal for details.":
        "Установка завершилась ошибкой или была отменена. Подробности — в отдельном терминале.",
    "Could not detect CiderDarling": "Не удалось обнаружить CiderDarling",
    "The installer finished, but the runtime could not be detected. Check the terminal output.":
        "Установщик завершил работу, но среда не обнаружена. Проверьте вывод терминала.",
    "CiderDarling installed. Apply the runtime choice to switch.":
        "CiderDarling установлена. Примените выбор среды, чтобы переключиться.",
    "Darling runtime": "Среда Darling",
    "DarlingHQ's Darling": "Darling от DarlingHQ",
    "QuadraHQ's CiderDarling": "CiderDarling от QuadraHQ",
    "Each runtime keeps its own Roblox sign-in.": "Каждая среда сохраняет свой вход в Roblox.",
    "{runtime} (not installed)": "{runtime} (не установлена)",
    "Active runtime": "Активная среда",
    "Apply and restart Quadra": "Применить и перезапустить Quadra",
    "Refresh installed runtimes": "Обновить список установленных сред",
    "Flatpak uses its bundled Darling runtime.": "Flatpak использует встроенную среду Darling.",
    "Install this runtime with Quadra's installer before switching.":
        "Перед переключением установите эту среду через установщик Quadra.",
    "Could not inspect installed runtimes": "Не удалось проверить установленные среды",
    "Runtime saved. Close and reopen Quadra to apply it.": "Среда сохранена. Закройте и снова откройте Quadra, чтобы применить её.",
    "Could not switch Darling runtime": "Не удалось переключить среду Darling",
    "Quadra's launcher files are missing. Reinstall Quadra before restarting.":
        "Файлы лаунчера Quadra отсутствуют. Перед перезапуском установите Quadra заново.",
    "MangoHud overlay": "Оверлей MangoHud",
    "Show FPS, frametimes and CPU/GPU usage. Requires MangoHud; applies on next launch.":
        "FPS, время кадра и загрузка CPU/GPU. Требуется MangoHud; применяется при следующем запуске.",
    "Renderer": "Рендерер",
    "OpenGL": "OpenGL",
    "Vulkan (Zink, experimental)": "Vulkan (Zink, экспериментальный)",
    "Installing Vulkan dependencies… Authorize the administrator prompt to continue.":
        "Устанавливаются зависимости Vulkan… Подтвердите запрос администратора для продолжения.",
    "Could not install Vulkan dependencies": "Не удалось установить зависимости Vulkan",
    "Vulkan dependencies installed": "Зависимости Vulkan установлены",
    "Applies on next launch. Missing Mesa EGL/Zink packages need administrator authentication.":
        "Применяется при следующем запуске. Для установки недостающих Mesa EGL/Zink нужна авторизация администратора.",
    "Applies on next launch. Vulkan uses Mesa Zink and a hardware Vulkan driver.":
        "Применяется при следующем запуске. Для Vulkan нужны Mesa Zink и аппаратный драйвер Vulkan.",
    # Pages
    "Play": "Играть",
    "Fast flags": "Фастфлаги",
    "Settings": "Настройки",
    "Environment": "Окружение",
    "Mods": "Моды",
    "Info": "Инфо",
    # The desktop: top bar, play window, menu and console
    "console": "консоль",
    "menu": "меню",
    "find us": "мы здесь",
    "Account": "Аккаунт",
    "Time in this game": "Время в этой игре",
    "not installed": "не установлен",
    "running": "работает",
    "starts with the game": "запустится с игрой",
    "signed in": "вход выполнен",
    "not signed in": "вход не выполнен",
    "playing": "в игре",
    "starting": "запускается",
    "busy": "занят",
    "not running": "не запущен",
    "missing: {programs}": "не хватает: {programs}",
    "install them, then press play": "установите их и нажмите «Играть»",
    "darling and the build tools are installed": "darling и инструменты сборки установлены",
    "roblox {version} is installed": "roblox {version} установлен",
    "roblox is not installed yet": "roblox ещё не установлен",
    "the shim is built": "шим собран",
    "the shim builds on the first start": "шим соберётся при первом запуске",
    "darling is running": "darling работает",
    "darling starts with the game": "darling запустится вместе с игрой",
    "sound goes through {server}": "звук идёт через {server}",
    "no pw-cat or pacat: the game will be silent": "нет pw-cat и pacat: игра будет без звука",
    "the sign-in window is ready": "окно входа готово",
    "WebKitGTK 6.0 is not installed: sign in with Quick Login":
        "WebKitGTK 6.0 не установлен: входите через Quick Login",
    "signed in to roblox": "вход в roblox выполнен",
    "not signed in: sign in inside roblox": "вход не выполнен: войдите внутри roblox",
    "roblox is running": "roblox запущен",
    "starting roblox…": "roblox запускается…",
    "install the missing programs first": "сначала установите недостающие программы",
    "press install roblox": "нажмите «Установить Roblox»",
    "press play": "нажмите «Играть»",
    # Launcher update
    "Update available": "Доступно обновление",
    "A new version of Quadra ({version}) is available. Update now?":
        "Доступна новая версия Quadra ({version}). Обновить сейчас?",
    "Later": "Позже",
    "Update": "Обновить",
    "Launcher version": "Версия лаунчера",
    "Force update": "Принудительное обновление",
    "Quadra is up to date": "Установлена последняя версия Quadra",
    "Update {version} available": "Доступно обновление {version}",
    "Pulling latest version…": "Загрузка последней версии…",
    "Building shim…": "Сборка шима…",
    "Updating launcher shortcuts…": "Обновление ярлыков лаунчера…",
    "Quadra updated successfully": "Quadra успешно обновлён",
    "Quadra updated. Restart it to use the new version.":
        "Quadra обновлён. Перезапусти его, чтобы открыть новую версию.",
    "Could not update the files in {path}:\n{output}": "Не удалось обновить файлы в {path}:\n{output}",
    # Play page
    "Roblox {version}": "Roblox {version}",
    "Roblox not found": "Roblox не найден",
    "Darling running": "Darling запущен",
    "Darling starts with the game": "Darling запустится при старте",
    "Roblox is running": "Roblox запущен",
    "Starting…": "Запускаю…",
    "Stop Roblox": "Остановить Roblox",
    "Could not start Roblox": "Не удалось запустить Roblox",
    "Update failed": "Обновление не удалось",
    "Copy": "Скопировать",
    "Install these first: {programs}": "Сначала установи: {programs}",
    "Close": "Закрыть",
    "Install Roblox": "Установить Roblox",
    "Sign in with Quick Login": "Входи через Quick Login",
    "Roblox closed at the captcha": "Roblox закрылся на капче",
    "Signing up and signing in with a password show a captcha in a built-in browser. "
    "The launcher shows it in a window of its own when WebKitGTK 6.0 is installed "
    "(webkitgtk-6.0, gir1.2-webkit-6.0 or webkitgtk6.0). Without it, create the "
    "account on roblox.com, then sign in with Quick Login: Roblox shows a code, "
    "enter it on a phone or in a browser where you are already signed in.":
        "Регистрация и вход по паролю показывают капчу во встроенном браузере. Лаунчер "
        "открывает её в своём окне, если установлен WebKitGTK 6.0 (webkitgtk-6.0, "
        "gir1.2-webkit-6.0 или webkitgtk6.0). Без него создай аккаунт на roblox.com, потом "
        "войди через Quick Login: Roblox покажет код, введи его на телефоне или в браузере, "
        "где ты уже вошёл.",
    "Back": "Назад",
    "Forward": "Вперёд",
    "Reload": "Обновить",
    "Back to Roblox": "Вернуться в Roblox",
    "Close": "Закрыть",
    "OK": "Понятно",
    "Roblox Studio": "Roblox Studio",
    "Roblox Studio is already running": "Roblox Studio уже запущен",
    "Install Roblox Studio?": "Установить Roblox Studio?",
    "Studio runs in its Windows version through Wine. Quadra downloads Wine, "
    "DXVK and Studio, about 800 MB.":
        "Studio запускается в Windows-версии через Wine. Quadra скачает Wine, "
        "DXVK и Studio, это около 800 МБ.",
    "Install": "Установить",
    "Could not start Roblox Studio": "Не удалось запустить Roblox Studio",
    "Starting Roblox Studio…": "Запускаю Roblox Studio…",
    "{label}: {done} of {total} MB": "{label}: {done} из {total} МБ",
    "Unpacking Wine": "Распаковываю Wine",
    "Preparing Wine": "Готовлю Wine",
    "Roblox Studio: {done} of {total} MB": "Roblox Studio: {done} из {total} МБ",
    "Unknown Studio package manifest format": "Неизвестный формат манифеста пакетов Studio",
    "{name} failed its checksum": "{name} не прошёл проверку контрольной суммы",
    "Open last log": "Открыть последний лог",
    "Roblox exited with code {status}": "Roblox завершился с кодом {status}",
    # Fast flags
    "FPS limit": "Лимит FPS",
    "Graphics quality": "Качество графики",
    "No shadows": "Без теней",
    "No grass": "Без травы",
    "Low quality terrain": "Упрощённый рельеф",
    "Texture quality override": "Качество текстур",
    "Popular": "Популярные",
    "Roblox only applies flags from its allowlist, some flags may have no effect.":
        "Roblox применяет только флаги из своего списка разрешённых, часть флагов может не действовать.",
    "Custom flags": "Свои флаги",
    "Add flag": "Добавить флаг",
    "Import JSON": "Импорт JSON",
    "Export JSON": "Экспорт JSON",
    "File": "Файл",
    "New flag": "Новый флаг",
    "Name": "Название",
    "Value": "Значение",
    "Remove": "Удалить",
    "Import fast flags": "Импорт фастфлагов",
    "Export fast flags": "Экспорт фастфлагов",
    "Copy flags to clipboard or save to a file.": "Скопируй флаги в буфер обмена или сохрани в файл.",
    "Flags copied to clipboard": "Флаги скопированы в буфер обмена",
    "Save to file…": "Сохранить в файл…",
    "Save fast flags": "Сохранить фастфлаги",
    "Save": "Сохранить",
    "Flags saved to {path}": "Флаги сохранены в {path}",
    "Reset all fast flags": "Сбросить все фастфлаги",
    "Reset all fast flags?": "Сбросить все фастфлаги?",
    "All custom flags and presets will be cleared and reset to default.":
        "Все кастомные флаги и пресеты будут очищены и сброшены по умолчанию.",
    "Reset": "Сбросить",
    "All fast flags have been reset": "Все фастфлаги сброшены",
    'Paste JSON like {"Flag": value}. Flags are added to the current ones.':
        'Вставь JSON вида {"Флаг": значение}. Флаги добавятся к текущим.',
    "Cancel": "Отмена",
    "Select": "Выбрать",
    "Import": "Импортировать",
    "This is not a JSON object with flags": "Это не JSON-объект с флагами",
    "Imported flags: {count}": "Импортировано флагов: {count}",
    "Could not save flags: {error}": "Не удалось сохранить флаги: {error}",
    # Settings: game
    "Game": "Игра",
    "Roblox UI scale": "Масштаб интерфейса Roblox",
    "100–400%. Applies on next launch.": "100–400%. Применяется при следующем запуске.",
    "Camera sensitivity": "Чувствительность камеры",
    "Mouse movement multiplier while rotating the camera":
        "Множитель движения мыши при вращении камеры",
    "Scroll sensitivity": "Чувствительность колёсика",
    "Mouse wheel scroll speed in menus and interface":
        "Скорость прокрутки колёсика мыши в меню и интерфейсе",
    "Show the launcher after Roblox exits": "Показывать лаунчер после выхода из Roblox",
    "Hide launcher while playing": "Скрывать лаунчер во время игры",
    "Raw mouse input": "Сырой ввод мыши",
    "Camera moves by the mouse's own motion, without pointer acceleration (XInput 2)":
        "Камера следует за движением самой мыши, без ускорения указателя (XInput 2)",
    "Hide the launcher window while the game is running": "Скрывать окно лаунчера, пока запущена игра",
    "Discord Rich Presence": "Discord Rich Presence",
    "Enable Discord Rich Presence": "Включить Discord Rich Presence",
    "Show current game and playtime in your Discord status": "Показывать статус игры и время в Discord",
    "Show experience name in Discord": "Показывать название игры в Discord",
    "Display the title and creator of the place you are playing":
        "Отображать название и создателя плейса, в который вы играете",
    "Show experience thumbnail in Discord": "Показывать иконку плейса в Discord",
    "Replace the Quadra icon with the game's icon":
        "Заменять иконку Quadra на обложку игры",
    "Show elapsed time in Discord": "Показывать прошедшее время в Discord",
    "Display how long you have been playing in your status":
        "Отображать время, прошедшее с момента запуска игры",
    "Show playtime": "Показывать время в игре",
    "Show accumulated playtime on the Play page": "Отображать наигранное время на вкладке «Играть»",
    "Total playtime": "Всего наиграно",
    "Playing Roblox": "Играет в Roblox",
    "In Game": "В игре",
    "In Main Menu": "В главном меню",
    "by {creator}": "от {creator}",
    "Get Quadra": "Скачать Quadra",
    "Game page": "Страница игры",
    "Hide the macOS menu bar": "Скрывать полоску меню macOS",
    "The Roblox, Edit, Window… strip at the top of the game window":
        "Полоска Roblox, Edit, Window… сверху окна игры",
    # Settings: DNS
    "DNS for Roblox": "DNS для Roblox",
    "Only Roblox uses this server, the rest of the system keeps its own DNS. "
    "Helps when some Roblox images or servers do not load.":
        "Этот сервер использует только Roblox, остальная система остаётся на своём DNS. "
        "Помогает, если не грузятся картинки или сервера Roblox.",
    "DNS server": "DNS-сервер",
    "System (Darling default)": "Системный (как в Darling)",
    "Quad9 (9.9.9.9, encrypted)": "Quad9 (9.9.9.9, шифрованный)",
    "Cloudflare (1.1.1.1, encrypted)": "Cloudflare (1.1.1.1, шифрованный)",
    "Google (8.8.8.8, encrypted)": "Google (8.8.8.8, шифрованный)",
    "Custom": "Свой",
    "Custom server": "Свой сервер",
    "IP address, optionally with :port. Plain DNS, not encrypted.":
        "IP-адрес, можно с :портом. Обычный DNS, без шифрования.",
    "Custom DNS server must look like 9.9.9.9, 9.9.9.9:53 or [2620:fe::fe]:53":
        "Свой DNS-сервер пишется так: 9.9.9.9, 9.9.9.9:53 или [2620:fe::fe]:53",
    # Settings: language
    "Interface": "Интерфейс",
    "Language": "Язык",
    # Settings: Roblox
    "Installed version": "Установленная версия",
    "not found": "не найдена",
    "Check for updates": "Проверить обновления",
    "Checking…": "Проверяю…",
    "Updating…": "Обновляю…",
    "Could not check: {error}": "Не удалось проверить: {error}",
    "The latest version is installed": "Установлена последняя версия",
    "Update to {version}": "Обновить до {version}",
    "Close Roblox first": "Сначала закрой Roblox",
    "Please wait, the launcher is busy": "Подожди, лаунчер ещё занят",
    "Darling could not create its prefix in {path}": "Darling не смог создать префикс в {path}",
    "Roblox updated, the old version is in backups/": "Roblox обновлён, старая версия в backups/",
    "Roblox installed": "Roblox установлен",
    "Downloading {done} of {total} MB": "Загрузка {done} из {total} МБ",
    "Unpacking": "Распаковка",
    "Roblox returned 403; trying Quadra's download server":
        "Roblox вернул 403; пробуем сервер загрузок Quadra",
    "Done": "Готово",
    "The download is not a zip archive": "Скачанный файл не является zip-архивом",
    "The archive has no RobloxPlayer.app": "В архиве нет RobloxPlayer.app",
    "Check for Roblox updates on startup": "Проверять обновления Roblox при запуске",
    "Prompt to update if a newer version of Roblox is available": "Предлагать обновить, если доступна новая версия Roblox",
    "Delete Roblox": "Удалить Roblox",
    "Delete Roblox?": "Удалить Roblox?",
    "RobloxPlayer.app and all mod modifications will be removed from your computer.":
        "RobloxPlayer.app и все файлы модов будут удалены с компьютера.",
    "Roblox is not installed": "Roblox не установлен",
    "Roblox deleted successfully": "Roblox успешно удалён",
    "Delete": "Удалить",
    "Roblox update available": "Доступно обновление Roblox",
    "A newer version of Roblox ({version}) is available. Update now?":
        "Доступна новая версия Roblox ({version}). Обновить сейчас?",
    # Mods
    "Sound presets": "Звуковые пресеты",
    "Death sound": "Звук смерти",
    "Choose the sound played when your character resets or dies":
        "Звук при гибели персонажа или сбросе",
    "Default (Roblox)": "По умолчанию (Roblox)",
    "Classic OOF": "Классический OOF",
    "Custom sound": "Свой звук",
    "Custom death sound file": "Файл звука смерти",
    "No file chosen": "Файл не выбран",
    "Choose…": "Выбрать…",
    "Select custom death sound (.ogg)": "Выбрать файл звука смерти (.ogg)",
    "Classic movement sounds": "Классические звуки движения",
    "Restores 2006-2014 walking, jumping, getting up, and silent landing sounds":
        "Возвращает звуки ходьбы, прыжка, подъёма и тихого приземления (2006–2014)",
    "Mouse cursors": "Курсоры мыши",
    "Cursor style": "Стиль курсора",
    "Replaces in-game mouse cursors": "Заменяет игровые курсоры мыши",
    "Default": "По умолчанию",
    "2006 Classic": "Классический 2006",
    "2013 Retro": "Ретро 2013",
    "Black & White Dot": "Чёрно-белая точка",
    "Purple Cross": "Фиолетовый крест",
    "Custom cursor": "Свой курсор",
    "Custom cursor file or folder": "Файл или папка своего курсора",
    "Select custom cursor (.png or folder)": "Выбрать курсор (.png или папку)",
    "Typography": "Типографика",
    "Custom font": "Кастомный шрифт",
    "Choose font…": "Выбрать шрифт…",
    "Clear font": "Сбросить шрифт",
    "Select font (.ttf, .otf)": "Выбрать файл шрифта (.ttf, .otf)",
    "No custom font selected": "Используются стандартные шрифты Roblox",
    "User modifications": "Пользовательские модификации",
    "Enable modifications folder": "Включить папку модификаций",
    "Overlay files from modifications/ onto the Roblox client":
        "Накладывать файлы из папки modifications/ поверх ресурсов Roblox",
    "Open modifications folder": "Открыть папку модификаций",
    "Drop your custom textures, sounds, and models here":
        "Поместите сюда свои текстуры, звуки или модели",
    "Open": "Открыть",
    "Management": "Управление",
    "Apply mods now": "Применить моды сейчас",
    "Reset all mods to default": "Сбросить все моды к стандартным",
    "Mods applied": "Моды успешно применены",
    "All mods have been reset": "Все моды сброшены к оригиналу",
    "Error applying mods": "Ошибка применения модов",
    "Error resetting mods": "Ошибка сброса модов",
    # Settings: account
    "Account": "Аккаунт",
    "Sign out": "Выйти из аккаунта",
    "Sign out?": "Выйти из аккаунта?",
    "The saved Roblox session will be deleted, you will need to sign in again next time.":
        "Сохранённая сессия Roblox будет удалена, при следующем запуске нужно будет войти заново.",
    "Sign out of Roblox": "Выйти",
    "Session deleted": "Сессия удалена",
    "Could not sign out": "Не удалось выйти",
    "The saved session is still there. Press Restart Darling in Diagnostics and try again.":
        "Сохранённая сессия осталась на месте. Нажми «Перезапустить Darling» в разделе «Диагностика» "
        "и попробуй ещё раз.",
    # Settings: diagnostics
    "Diagnostics": "Диагностика",
    "Detailed logs for debugging. They slow the game down, enable only when needed.":
        "Подробные логи для отладки. Замедляют игру, включай только когда нужно.",
    "Backtrace on crashes": "Бэктрейс при крашах",
    "Network tracing (UDP)": "Трассировка сети (UDP)",
    "Mouse lock tracing": "Трассировка захвата мыши",
    "Mouse event tracing": "Трассировка событий мыши",
    "OpenGL tracing": "Трассировка OpenGL",
    "Frame rate in the log": "FPS в логе",
    "Keyboard tracing": "Трассировка клавиатуры",
    "Open logs folder": "Открыть папку с логами",
    "Could not open the logs folder: {error}": "Не удалось открыть папку с логами: {error}",
    "Rebuild shim": "Пересобрать шим",
    "Building the shim…": "Собираю шим…",
    "Shim built": "Шим собран",
    "The shim comes built with this package": "Шим в этом пакете уже собран",
    "Could not build the shim": "Не удалось собрать шим",
    "Could not build the shim:\n{output}": "Не удалось собрать шим:\n{output}",
    "Cannot connect to X11 display {display}. Make sure an X server or Xwayland is running.":
        "Не удалось подключиться к X11-дисплею {display}. Убедитесь, что запущен X-сервер или Xwayland.",
    "Restart Darling": "Перезапустить Darling",
    "Darling stopped, it starts with the next game": "Darling остановлен, запустится при следующей игре",
    "Could not restart Darling: {error}": "Не удалось перезапустить Darling: {error}",
    "Rebuilding the shim…": "Пересобираю шим…",
    "Restarting Darling…": "Перезапускаю Darling…",
    "Install the throttle patch": "Установить патч троттлинга",
    "Remove the throttle patch": "Удалить патч троттлинга",
    "Applied: the menu renders at full speed from the first second":
        "Применён: меню рендерится на полной скорости с первой секунды",
    "Not applied: the menu may run at ~3 FPS for the first 10 seconds":
        "Не применён: меню может работать на ~3 FPS первые 10 секунд",
    "Not available for this Roblox build": "Недоступно для этой сборки Roblox",
    "Apply the throttle patch automatically": "Применять патч троттлинга автоматически",
    "Patch the client on every launch and after Roblox updates":
        "Патчить клиента при каждом запуске и после обновлений Roblox",
    "Throttle patch": "Патч троттлинга",
    "Checking…": "Проверяю…",
    "Throttle patch failed": "Не удалось применить патч троттлинга",
    # Live logs view
    "Logs": "Логи",
    "Game Logs": "Логи игры",
    "Auto-scroll": "Автопрокрутка",
    "Copy logs": "Скопировать логи",
    "Logs copied to clipboard": "Логи скопированы в буфер обмена",
    "Clear view": "Очистить экран",
    "Open log file": "Открыть файл лога",
    "Open in editor": "Открыть в редакторе",
    "Open in text editor": "Открыть в текстовом редакторе",
    "Search in logs (Ctrl+F)…": "Поиск по логам (Ctrl+F)…",
    "Search in logs (Ctrl+F)": "Поиск по логам (Ctrl+F)",
    "Previous match": "Предыдущее совпадение",
    "Next match": "Следующее совпадение",
    "Close search": "Закрыть поиск",
    "No matches": "Нет совпадений",
    "No log found": "Файл лога не найден",
    "Could not open the log: {error}": "Не удалось открыть лог: {error}",
    "Game is not running": "Игра не запущена",
    "View game logs": "Просмотр логов игры",
    # Crash / X11 handling
    "X11 Connection Lost": "Потеряно соединение с X11",
    "The game crashed because the X11 connection was broken. This usually happens when raw mouse input overloads the display server with events. Would you like to disable raw mouse input?":
        "Игра аварийно закрылась из-за разрыва соединения с X11. Обычно это происходит, когда сырой ввод мыши (XInput 2) перегружает сервер Xwayland событиями движения. Отключить сырой ввод мыши?",
    "Keep Enabled": "Оставить включённым",
    "Disable Raw Mouse": "Отключить сырой ввод",
    "Raw mouse input disabled": "Сырой ввод мыши отключён",
    "The game crashed because the X11 connection was broken (explicit kill or server shutdown).":
        "Игра аварийно закрылась из-за разрыва соединения с X11 (сервер X11 был принудительно остановлен).",
    # Fast flags
    "Anisotropic filtering (16x)": "Анизотропная фильтрация (16x)",
    "Force maximum texture resolution": "Принудительное максимальное разрешение текстур",
    # Info
    "Quadra runs the real Roblox client for macOS on Linux through Darling. "
    "It is not made by Roblox and is not affiliated with it.":
        "Quadra запускает настоящий клиент Roblox для macOS на Linux через Darling. "
        "Его делает не Roblox, и с Roblox он никак не связан.",
    "Community": "Сообщество",
    "Authors": "Авторы",
    "{user} on Roblox": "{user} в Roblox",
    "Better UI, Mods": "Улучшенный интерфейс, моды",
    "Maintains this version: stability and performance fixes":
        "Поддерживает эту версию: стабильность и скорость",
    "Made with Claude Opus 5.5": "Сделано с Claude Opus 5.5",
    "Anthropic's AI wrote the code together with the authors": "ИИ от Anthropic писал код вместе с авторами",
    # CiderDarling settings and updates
    "CiderDarling settings": "Настройки CiderDarling",
    "Graphics card, watchdog, tracing and diagnostics": "Видеокарта, сторожевой таймер, трассировка и диагностика",
    "Update CiderDarling": "Обновить CiderDarling",
    "Update in terminal": "Обновить в терминале",
    "Installed {installed}, Quadra uses {pinned}. Opens a separate terminal for the build and sudo prompts.":
        "Установлена {installed}, Quadra использует {pinned}. Откроет отдельный терминал для сборки и запросов sudo.",
    "These settings apply while CiderDarling is the active runtime. The renderer "
    "and graphics card are shared with Environment → Game.":
        "Эти настройки действуют, пока CiderDarling — активная среда. Рендерер и видеокарта "
        "общие с разделом «Окружение → Игра».",
    "Installed revision": "Установленная ревизия",
    "{installed}; Quadra uses {pinned}": "{installed}; Quadra использует {pinned}",
    "unknown": "неизвестно",
    "{runtime}. Switch in Environment → Darling to use these settings.":
        "{runtime}. Переключите среду в разделе «Окружение → Darling», чтобы применить эти настройки.",
    "Graphics": "Графика",
    "Threads": "Потоки",
    "Watchdog thread kicks": "Пробуждение зависших потоков",
    "MACOBLOX_KICK. Interrupts threads stuck in long waits. Off by default: "
    "each kick costs time. Applies on next launch.":
        "MACOBLOX_KICK. Прерывает потоки, надолго застрявшие в ожидании. По умолчанию выключено: "
        "каждое прерывание стоит времени. Применяется при следующем запуске.",
    "Record runtime trace": "Записывать трассировку среды",
    "CIDER_TRACE_FILE. Numeric timings, no game text, in a private file in the logs "
    "folder (up to 32 MB per launch). Applies on next launch.":
        "CIDER_TRACE_FILE. Только числовые замеры, без текста игры, в личном файле в папке логов "
        "(до 32 МБ за запуск). Применяется при следующем запуске.",
    "Verbose darlingserver log": "Подробный лог darlingserver",
    "DSERVER_LOG_LEVEL=debug. dserver.log grows quickly; applies the next time "
    "Darling starts.":
        "DSERVER_LOG_LEVEL=debug. dserver.log быстро растёт; применяется при следующем запуске Darling.",
    "Open prefix folder": "Открыть папку префикса",
    "Could not open the prefix folder: {error}": "Не удалось открыть папку префикса: {error}",
    "CiderDarling is not installed": "CiderDarling не установлена",
    "End of the build log:": "Конец лога сборки:",
    "CiderDarling updated. Apply and restart Quadra to use it.":
        "CiderDarling обновлена. Примените выбор и перезапустите Quadra, чтобы использовать её.",
    # Diagnostics archive
    "Collect diagnostics": "Собрать диагностику",
    "Allow freeze diagnostics": "Разрешить диагностику зависаний",
    "MACOBLOX_ALLOW_DEBUGGER. Lets Collect diagnostics read the game's thread stacks; "
    "turn on before starting the game.":
        "MACOBLOX_ALLOW_DEBUGGER. Позволяет сбору диагностики читать стеки потоков игры; "
        "включите до запуска игры.",
    "Diagnostics are being collected…": "Диагностика уже собирается…",
    "Collecting diagnostics… This can take up to a minute.": "Сбор диагностики… Это может занять до минуты.",
    "Could not collect diagnostics": "Не удалось собрать диагностику",
    "Diagnostics collected": "Диагностика собрана",
    "Saved {name}. Attach it to your report; it leaves out sign-in data and join tickets.":
        "Сохранено: {name}. Приложите файл к отчёту; данных входа и билетов подключения в нём нет.",
    "Thread stacks need Allow freeze diagnostics (Settings → Environment → "
    "Diagnostics) to be on before the game starts.":
        "Для стеков потоков включите «Разрешить диагностику зависаний» (Настройки → Окружение → "
        "Диагностика) до запуска игры.",
    "Open folder": "Открыть папку",
    "Could not open the folder: {error}": "Не удалось открыть папку: {error}",
    # Server location
    "Show server location": "Показывать расположение сервера",
    "Sends the game server's IP address to RoValra (apis.rovalra.com) while you play":
        "Во время игры отправляет IP-адрес игрового сервера сервису RoValra (apis.rovalra.com)",
}


def set_language(code):
    global _language
    _language = code if code in LANGUAGES else "en"


def language():
    return _language


def _(text, **values):
    if _language == "ru":
        text = RU.get(text, text)
    return text.format(**values) if values else text
