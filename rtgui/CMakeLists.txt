# Common source files for both CLI and non-CLI execautables
set(CLISOURCEFILES
    alignedmalloc.cc
    edit.cc
    main-cli.cc
    multilangmgr.cc
    options.cc
    paramsedited.cc
    pathutils.cc
    threadutils.cc
    fastexport.cc
    exiffiltersettings.cc
    makeicc.cc
    )

set(NONCLISOURCEFILES
    liveparamcontroller.cc
    liveparamserver.cc
    numericcontrols.cc
    chatconnection.cc
    chatinput.cc
    chatpanel.cc
    adjuster.cc
    alignedmalloc.cc
    batchqueue.cc
    batchqueuebuttonset.cc
    batchqueueentry.cc
    batchqueuepanel.cc
    bayerpreprocess.cc
    bayerprocess.cc
    bayerrawexposure.cc
    blackwhite.cc
    bqentryupdater.cc
    browserfilter.cc
    cacheimagedata.cc
    cachemanager.cc
    cacorrection.cc
    checkbox.cc
    chmixer.cc
    clipboard.cc
    coarsepanel.cc
    coloredbar.cc
    coordinateadjuster.cc
    crop.cc
    crophandler.cc
    cropwindow.cc
    cursormanager.cc
    curveeditor.cc
    curveeditorgroup.cc
    darkframe.cc
    defringe.cc
    diagonalcurveeditorsubgroup.cc
    dirbrowser.cc
    denoise.cc
    distortion.cc
    dynamicprofilepanel.cc
    edit.cc
    editorpanel.cc
    editwindow.cc
    textureboost.cc
    exiffiltersettings.cc
    exifpanel.cc
    extprog.cc
    filebrowser.cc
    filebrowserentry.cc
    filecatalog.cc
    filepanel.cc
    filethumbnailbuttonset.cc
    filmsimulation.cc
    filterpanel.cc
    flatcurveeditorsubgroup.cc
    flatfield.cc
    gradient.cc
    guiutils.cc
    histogrampanel.cc
    history.cc
    icmpanel.cc
    ilabel.cc
    imagearea.cc
    imageareapanel.cc
    impulsedenoise.cc
    indclippedpanel.cc
    inspector.cc
    iptcpanel.cc
    labcurve.cc
    lensgeom.cc
    lensprofile.cc
    lockablecolorpicker.cc
    lwbutton.cc
    lwbuttonset.cc
    multilangmgr.cc
    mycurve.cc
    mydiagonalcurve.cc
    myflatcurve.cc
    navigator.cc
    options.cc
    paramsedited.cc
    partialpastedlg.cc
    pathutils.cc
    pcvignette.cc
    perspective.cc
    placesbrowser.cc
    popupbutton.cc
    popupcommon.cc
    popuptogglebutton.cc
    preferences.cc
    preprocess.cc
    previewhandler.cc
    previewloader.cc
    previewmodepanel.cc
    previewwindow.cc
    profilepanel.cc
    profilestorecombobox.cc
    prsharpening.cc
    rawcacorrection.cc
    rawexposure.cc
    recentbrowser.cc
    resize.cc
    rgbcurves.cc
    rotate.cc
    rtimage.cc
    rtsurface.cc
    rtscalable.cc
    rtwindow.cc
    saveasdlg.cc
    saveformatpanel.cc
    sensorbayer.cc
    sensorxtrans.cc
    toneequalizer.cc
    sharpening.cc
    shcselector.cc
    soundman.cc
    splash.cc
    spot.cc
    threadutils.cc
    thresholdadjuster.cc
    thresholdselector.cc
    thumbbrowserbase.cc
    thumbbrowserentrybase.cc
    thumbimageupdater.cc
    thumbnail.cc
    tonecurve.cc
    toolbar.cc
    toolpanel.cc
    toolpanelcoord.cc
    dirtreeview.cc
    vignetting.cc
    whitebalance.cc
    xtransprocess.cc
    xtransrawexposure.cc
    zoompanel.cc
    fattaltonemap.cc
    localcontrast.cc
    eventmapper.cc
    metadatapanel.cc
    colorwheel.cc
    softlight.cc
    dehaze.cc
    logencoding.cc
    areamask.cc
    maskspanel.cc
    grain.cc
    smoothing.cc
    colorcorrection.cc
    fastexport.cc
    exposure.cc
    saturation.cc
    hslequalizer.cc
    filmnegative.cc
    dateentry.cc
    wbpresets.cc
    wbprovider.cc
    controllines.cc
    filecatalog_rename.cc
    focusmask.cc
    shortcutmanager.cc
    session.cc
    thumbimgcache.cc
    clutparamspanel.cc
    gdkcolormgmt.cc
    )

include_directories(BEFORE "${CMAKE_CURRENT_BINARY_DIR}")

# Use the project's existing environment for worktree builds; paths remain
# editable in the chat panel for installed applications and other machines.
set(ART_AGENT_SOURCE_DIR "${PROJECT_SOURCE_DIR}" CACHE PATH "Chat source root")
set(ART_AGENT_STORE_DIR "${PROJECT_SOURCE_DIR}/data/vector-store/t09"
    CACHE PATH "Existing chat retrieval store")
execute_process(COMMAND git -C "${PROJECT_SOURCE_DIR}" rev-parse --git-common-dir
    OUTPUT_VARIABLE _agent_git_dir OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET)
get_filename_component(_agent_repo "${_agent_git_dir}/.." ABSOLUTE
    BASE_DIR "${PROJECT_SOURCE_DIR}")
find_program(ART_AGENT_PYTHON NAMES python3 python
    HINTS "${PROJECT_SOURCE_DIR}/venv/bin" "${_agent_repo}/venv/bin")
if(NOT ART_AGENT_PYTHON)
    set(ART_AGENT_PYTHON "python3")
endif()
find_program(ART_AGENT_ANSWER_RUNTIME NAMES codex)
if(NOT ART_AGENT_ANSWER_RUNTIME)
    set(ART_AGENT_ANSWER_RUNTIME "")
endif()

if(APPLE)
    # A local .app redirects GTK's default module lookup into the bundle.
    # Packaged builds supply their cache through the launcher environment.
    pkg_get_variable(_gtk_binary_version gtk+-3.0 gtk_binary_version)
    find_file(ART_GTK_IM_MODULE_FILE NAMES immodules.cache
        HINTS ${GTK_LIBRARY_DIRS}
        PATH_SUFFIXES "gtk-3.0/${_gtk_binary_version}"
        NO_DEFAULT_PATH)
    pkg_check_modules(MacIntegration gtk-mac-integration-gtk3)
    if(NOT MacIntegration_FOUND)
        find_package(MacIntegration REQUIRED)
    else()
        set(EXTRA_LIBDIR ${EXTRA_LIBDIR} ${MacIntegration_LIBDIR})
    endif()
    set(EXTRA_LIB_RTGUI ${MacIntegration_LIBRARIES})
    set(EXTRA_INCDIR ${EXTRA_INCDIR} ${MacIntegration_INCLUDE_DIRS})
endif()

if(WIN32)
    if (ART_USES_UCRT)
        message(STATUS "ucrt detected, setting locale to UTF8")
        set(EXTRA_SRC_CLI myicon.rc utf8.rc)
        set(EXTRA_SRC_NONCLI myicon.rc utf8.rc)
    else()
        set(EXTRA_SRC_CLI myicon.rc)
        set(EXTRA_SRC_NONCLI myicon.rc)
    endif()
    set(EXTRA_LIB_RTGUI winmm)
    include_directories(${EXTRA_INCDIR}
        ${GIOMM_INCLUDE_DIRS}
        ${GIO_INCLUDE_DIRS}
        ${GLIB2_INCLUDE_DIRS}
        ${GLIBMM_INCLUDE_DIRS}
        ${GTKMM_INCLUDE_DIRS}
        ${GTK_INCLUDE_DIRS}
        ${LENSFUN_INCLUDE_DIRS}
        ${RSVG_INCLUDE_DIRS}
        ${EXIV2_INCLUDE_DIRS}
        )
    link_directories(.
        ${EXTRA_LIBDIR}
        ${GIOMM_LIBRARY_DIRS}
        ${GIO_LIBRARY_DIRS}
        ${GLIB2_LIBRARY_DIRS}
        ${GLIBMM_LIBRARY_DIRS}
        ${GTKMM_LIBRARY_DIRS}
        ${GTK_LIBRARY_DIRS}
        ${LENSFUN_LIBRARY_DIRS}
        ${RSVG_LIBRARY_DIRS}
        )
else()
    include_directories(${EXTRA_INCDIR}
        ${CANBERRA-GTK_INCLUDE_DIRS}
        ${EXPAT_INCLUDE_DIRS}
        ${FFTW3F_LIBRARY_DIRS}
        ${GIOMM_INCLUDE_DIRS}
        ${GIO_INCLUDE_DIRS}
        ${GLIB2_INCLUDE_DIRS}
        ${GLIBMM_INCLUDE_DIRS}
        ${GOBJECT_INCLUDE_DIRS}
        ${GTHREAD_INCLUDE_DIRS}
        ${GTKMM_INCLUDE_DIRS}
        ${GTK_INCLUDE_DIRS}
        ${LCMS_INCLUDE_DIRS}
        ${LENSFUN_INCLUDE_DIRS}
        ${RSVG_INCLUDE_DIRS}
        ${EXIV2_INCLUDE_DIRS}
        )
    link_directories(${EXTRA_LIBDIR}
        ${CANBERRA-GTK_LIBRARY_DIRS}
        ${EXPAT_LIBRARY_DIRS}
        ${FFTW3F_LIBRARY_DIRS}
        ${GIOMM_LIBRARY_DIRS}
        ${GIO_LIBRARY_DIRS}
        ${GLIB2_LIBRARY_DIRS}
        ${GLIBMM_LIBRARY_DIRS}
        ${GOBJECT_LIBRARY_DIRS}
        ${GTHREAD_LIBRARY_DIRS}
        ${GTKMM_LIBRARY_DIRS}
        ${GTK_LIBRARY_DIRS}
        ${LCMS_LIBRARY_DIRS}
        ${LENSFUN_LIBRARY_DIRS}
        ${RSVG_LIBRARY_DIRS}
        )
endif()

# Excluding libatomic needed by Clang/FreeBSD, #3636
if(OPENMP_FOUND AND "${CMAKE_CXX_COMPILER_ID}" STREQUAL "GNU")
    set(EXTRA_LIB_RTGUI ${EXTRA_LIB_RTGUI} "atomic")
endif()

if(LIBRAW_FOUND)
    link_directories(${LIBRAW_LIBRARY_DIRS})
endif()
if(OCIO_FOUND)
    include_directories(${OCIO_INCLUDE_DIRS})
    link_directories(${OCIO_LIBRARY_DIRS})
endif()
if(CTL_FOUND)
    include_directories(${CTL_INCLUDE_DIRS})
endif()

if(SIMDE_INCLUDE_DIRS)
    include_directories("${SIMDE_INCLUDE_DIRS}")
endif()

# Shared GUI core library (excludes main.cc so art and macOS test_liveparam_gui share one build)
add_library(rtgui_core STATIC ${NONCLISOURCEFILES})
add_dependencies(rtgui_core UpdateInfo)
target_compile_definitions(rtgui_core PUBLIC GUIVERSION)
set_target_properties(rtgui_core PROPERTIES COMPILE_FLAGS "${CMAKE_CXX_FLAGS}")

# Create new executables targets
add_executable(art ${EXTRA_SRC_NONCLI} main.cc)
add_executable(art-cli ${EXTRA_SRC_CLI} ${CLISOURCEFILES})

# Add dependencies to executables targets
add_dependencies(art UpdateInfo)
add_dependencies(art-cli UpdateInfo)

#Define a target specific definition to use in code
target_compile_definitions(art PUBLIC GUIVERSION)
target_compile_definitions(art-cli PUBLIC CLIVERSION)

# Set executables targets properties, i.e. output filename and compile flags
# for "Debug" builds, open a console in all cases for Windows version
if((WIN32) AND NOT(UPPER_CMAKE_BUILD_TYPE STREQUAL "DEBUG"))
    set_target_properties(art PROPERTIES LINK_FLAGS "-mwindows")
endif()
set_target_properties(art PROPERTIES COMPILE_FLAGS "${CMAKE_CXX_FLAGS}" OUTPUT_NAME ART)
set_target_properties(art-cli PROPERTIES COMPILE_FLAGS "${CMAKE_CXX_FLAGS}" OUTPUT_NAME ART-cli)

set(RTGUI_LINK_LIBRARIES
    rtgui_core
    rtengine
    ${CANBERRA-GTK_LIBRARIES}
    ${EXPAT_LIBRARIES}
    ${EXTRA_LIB_RTGUI}
    ${FFTW3F_LIBRARIES}
    ${GIOMM_LIBRARIES}
    ${GIO_LIBRARIES}
    ${GLIB2_LIBRARIES}
    ${GLIBMM_LIBRARIES}
    ${GOBJECT_LIBRARIES}
    ${GTHREAD_LIBRARIES}
    ${GTKMM_LIBRARIES}
    ${GTK_LIBRARIES}
    ${JPEG_LIBRARIES}
    ${LCMS_LIBRARIES}
    ${PNG_LIBRARIES}
    ${TIFF_LIBRARIES}
    ${ZLIB_LIBRARIES}
    ${LENSFUN_LIBRARIES}
    ${RSVG_LIBRARIES}
    ${EXIV2_LIBRARIES}
    )

# Add linked libraries dependencies to executables targets
target_link_libraries(art PUBLIC ${RTGUI_LINK_LIBRARIES})

target_link_libraries(art-cli PUBLIC
    rtengine
    ${CAIROMM_LIBRARIES}
    ${EXPAT_LIBRARIES}
    ${EXTRA_LIB_RTGUI}
    ${FFTW3F_LIBRARIES}
    ${GIOMM_LIBRARIES}
    ${GIO_LIBRARIES}
    ${GLIB2_LIBRARIES}
    ${GLIBMM_LIBRARIES}
    ${GOBJECT_LIBRARIES}
    ${GTHREAD_LIBRARIES}
    ${JPEG_LIBRARIES}
    ${LCMS_LIBRARIES}
    ${PNG_LIBRARIES}
    ${TIFF_LIBRARIES}
    ${ZLIB_LIBRARIES}
    ${LENSFUN_LIBRARIES}
    ${RSVG_LIBRARIES}
    ${EXIV2_LIBRARIES}
    )

if(HAS_MIMALLOC)
    target_link_libraries(art PUBLIC mimalloc)
    target_link_libraries(art-cli PUBLIC mimalloc)
endif()

if(APPLE)
    target_link_libraries(art PRIVATE "-framework ApplicationServices -framework Foundation")
    target_link_libraries(art-cli PRIVATE "-framework Foundation")
endif()

if(APPLE)
    add_executable(test_liveparam test_liveparam.cc liveparamcontroller.cc liveparamserver.cc)
    target_compile_definitions(test_liveparam PUBLIC GUIVERSION)
    target_link_libraries(test_liveparam PUBLIC
        rtengine
        ${CAIROMM_LIBRARIES}
        ${EXPAT_LIBRARIES}
        ${EXTRA_LIB_RTGUI}
        ${FFTW3F_LIBRARIES}
        ${GIOMM_LIBRARIES}
        ${GIO_LIBRARIES}
        ${GLIB2_LIBRARIES}
        ${GLIBMM_LIBRARIES}
        ${GOBJECT_LIBRARIES}
        ${GTHREAD_LIBRARIES}
        ${GTKMM_LIBRARIES}
        ${GTK_LIBRARIES}
        ${JPEG_LIBRARIES}
        ${LCMS_LIBRARIES}
        ${PNG_LIBRARIES}
        ${TIFF_LIBRARIES}
        ${ZLIB_LIBRARIES}
        ${LENSFUN_LIBRARIES}
        ${RSVG_LIBRARIES}
        ${EXIV2_LIBRARIES}
        )
    target_link_libraries(test_liveparam PRIVATE "-framework ApplicationServices -framework Foundation")

    add_executable(test_liveparam_gui test_liveparam_gui.cc test_liveparam_socket.cc test_numericwidgets.cc)
    add_dependencies(test_liveparam_gui UpdateInfo)
    target_compile_definitions(test_liveparam_gui PUBLIC GUIVERSION ART_TEST_SOURCE_DIR="${PROJECT_SOURCE_DIR}")
    set_target_properties(test_liveparam_gui PROPERTIES COMPILE_FLAGS "${CMAKE_CXX_FLAGS}")
    target_link_libraries(test_liveparam_gui PUBLIC ${RTGUI_LINK_LIBRARIES})
    if(HAS_MIMALLOC)
        target_link_libraries(test_liveparam_gui PUBLIC mimalloc)
    endif()
    target_link_libraries(test_liveparam_gui PRIVATE "-framework ApplicationServices -framework Foundation")

    # Exercise the real main.cc startup paths without forwarding files to an
    # unrelated, already running ART instance on the development desktop.
    add_executable(test_liveparam_app EXCLUDE_FROM_ALL main.cc)
    add_dependencies(test_liveparam_app UpdateInfo)
    target_compile_definitions(test_liveparam_app PRIVATE GUIVERSION
        ART_APPLICATION_ID="us.pixls.art.ART.liveparamtest")
    target_link_libraries(test_liveparam_app PRIVATE ${RTGUI_LINK_LIBRARIES}
        "-framework ApplicationServices -framework Foundation")
endif()

# Install executables
if(APPLE AND NOT APPLE_NEW_BUNDLE)
    install(TARGETS art DESTINATION "${PROJECT_SOURCE_DIR}/build/${CMAKE_BUILD_TYPE}/MacOS")
    install(TARGETS art-cli DESTINATION "${PROJECT_SOURCE_DIR}/build/${CMAKE_BUILD_TYPE}/MacOS")
else()
    install(TARGETS art DESTINATION ${BINDIR})
    install(TARGETS art-cli DESTINATION ${BINDIR})
endif()

# Create config.h which defines where data are stored
if(APPLE_NEW_BUNDLE)
    foreach(_v DATADIR DOCDIR CREDITSDIR LICENCEDIR LENSFUNDBDIR)
        if(${_v} AND NOT IS_ABSOLUTE "${${_v}}")
            set(${_v} "../../${${_v}}")
        endif()
    endforeach()
endif()
configure_file("${CMAKE_CURRENT_SOURCE_DIR}/config.h.in" "${CMAKE_CURRENT_BINARY_DIR}/config.h")
