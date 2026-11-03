/*
 *  This file is part of RawTherapee.
 *
 *  Copyright (c) 2004-2010 Gabor Horvath <hgabor@rawtherapee.com>
 *
 *  RawTherapee is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, either version 3 of the License, or
 *  (at your option) any later version.
 *
 *  RawTherapee is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with RawTherapee.  If not, see <http://www.gnu.org/licenses/>.
 */
#include "previewhandler.h"
#include "liveparamcontroller.h"
#include "../rtengine/rtengine.h"
#include <gtkmm.h>

using namespace rtengine;
using namespace rtengine::procparams;

PreviewHandler::PreviewHandler(): previewScale(1.) {}

PreviewHandler::~PreviewHandler()
{
    idle_register.destroy();
}

void PreviewHandler::setImage(IImage8 *image, double scale,
                              const procparams::CropParams &)
{
    MyMutex::MyLock lock(sourceMutex_);
    sourceImage_ = image;
    sourceScale_ = scale;
}

void PreviewHandler::delImage(IImage8 *image)
{
    MyMutex::MyLock lock(sourceMutex_);
    if (sourceImage_ == image) {
        sourceImage_ = nullptr;
    }
    // Displayed frames own their bytes and never refer to this engine buffer.
    image->free();
}

void PreviewHandler::imageReady(const procparams::CropParams &cp)
{
    imageReady(cp, ProcessingContext());
}

void PreviewHandler::imageReady(const procparams::CropParams &cp,
                                int64_t, int64_t)
{
    imageReady(cp, ProcessingContext());
}

void PreviewHandler::imageReady(const procparams::CropParams &cp,
                                const ProcessingContext &ctx)
{
    std::vector<unsigned char> pixels;
    int width, height;
    double scale;
    {
        MyMutex::MyLock sourceLock(sourceMutex_);
        if (!sourceImage_) {
            return;
        }
        MyMutex::MyLock imageLock(sourceImage_->getMutex());
        width = sourceImage_->getWidth();
        height = sourceImage_->getHeight();
        scale = sourceScale_;
        pixels.assign(sourceImage_->getData(),
                      sourceImage_->getData() + 3 * width * height);
    }
    idle_register.add([this, cp, ctx, pixels, width, height, scale]() -> bool {
        auto &controller = art::liveparam::LiveParamController::getInstance();
        if (editorPanel_ && !controller.acceptsFrame(editorPanel_, ctx)) {
            return false;
        }
        {
            MyMutex::MyLock lock(previewImgMutex);
            previewImg = Gdk::Pixbuf::create_from_data(pixels.data(),
                Gdk::COLORSPACE_RGB, false, 8, width, height, 3 * width)->copy();
            cropParams = cp;
            previewScale = scale;
            displayedContext_ = ctx;
        }
        previewImageChanged();
        if (editorPanel_) {
            controller.onPreviewReady(editorPanel_, ctx);
        }
        return false;
    });
}

void PreviewHandler::imageFailed(const ProcessingContext &ctx)
{
    idle_register.add([this, ctx]() -> bool {
        if (editorPanel_) {
            art::liveparam::LiveParamController::getInstance()
                .onRenderFailed(editorPanel_, ctx);
        }
        return false;
    });
}

Glib::RefPtr<Gdk::Pixbuf> PreviewHandler::getRoughImage(int x, int y, int w,
                                                        int h, double zoom)
{
    MyMutex::MyLock lock(previewImgMutex);

    Glib::RefPtr<Gdk::Pixbuf> resPixbuf;

    if (previewImg) {
        double totalZoom = zoom * previewScale;

        if (w > previewImg->get_width() * totalZoom) {
            w = previewImg->get_width() * totalZoom;
        }

        if (h > previewImg->get_height() * totalZoom) {
            h = previewImg->get_height() * totalZoom;
        }

        x *= zoom;
        y *= zoom;

        w = rtengine::LIM<int>(w, 0,
                               int(previewImg->get_width() * totalZoom) - x);
        h = rtengine::LIM<int>(h, 0,
                               int(previewImg->get_height() * totalZoom) - y);

        resPixbuf = Gdk::Pixbuf::create(Gdk::COLORSPACE_RGB, false, 8, w, h);
        previewImg->scale(resPixbuf, 0, 0, w, h, -x, -y, totalZoom, totalZoom,
                          Gdk::INTERP_NEAREST);
    }

    return resPixbuf;
}

Glib::RefPtr<Gdk::Pixbuf>
PreviewHandler::getRoughImage(int desiredW, int desiredH, double &zoom_)
{
    MyMutex::MyLock lock(previewImgMutex);

    Glib::RefPtr<Gdk::Pixbuf> resPixbuf;

    if (previewImg) {
        double zoom1 =
            (double)max(desiredW, 20) /
            previewImg
                ->get_width(); // too small values lead to extremely increased
                               // processing time in scale function, Issue 2783
        double zoom2 =
            (double)max(desiredH, 20) / previewImg->get_height(); // ""
        double zoom = zoom1 < zoom2 ? zoom1 : zoom2;

        resPixbuf = Gdk::Pixbuf::create(Gdk::COLORSPACE_RGB, false, 8,
                                        previewImg->get_width() * zoom,
                                        previewImg->get_height() * zoom);
        previewImg->scale(resPixbuf, 0, 0, previewImg->get_width() * zoom,
                          previewImg->get_height() * zoom, 0, 0, zoom, zoom,
                          Gdk::INTERP_BILINEAR);
        zoom_ = zoom / previewScale;
    }

    return resPixbuf;
}

void PreviewHandler::previewImageChanged()
{

    for (std::list<PreviewListener *>::iterator i = listeners.begin();
         i != listeners.end(); ++i) {
        (*i)->previewImageChanged();
    }
}
