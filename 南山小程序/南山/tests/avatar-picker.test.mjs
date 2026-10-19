import assert from 'node:assert/strict'
import test from 'node:test'
import { chooseAvatarImage } from '../subpackages/tech-transfer/api/avatar-picker.mjs'

test('WeChat uses the maintained media picker with images and album only', async () => {
  let options
  const path = await chooseAvatarImage({
    chooseMedia: input => { options = input; input.success({ tempFiles: [{ tempFilePath: 'wxfile://avatar.png', fileType: 'image' }] }) },
    chooseImage: () => assert.fail('must prefer chooseMedia'),
  })
  assert.equal(path, 'wxfile://avatar.png')
  assert.deepEqual(options.mediaType, ['image'])
  assert.deepEqual(options.sourceType, ['album'])
  assert.equal(options.count, 1)
})

test('older runtimes and H5 keep the image picker fallback', async () => {
  assert.equal(await chooseAvatarImage({ chooseImage: options => options.success({ tempFilePaths: ['blob:avatar'] }) }), 'blob:avatar')
})

test('WeChat picker failures and synchronous exceptions are observable', async () => {
  await assert.rejects(chooseAvatarImage({ chooseMedia: options => options.fail({ errMsg: 'chooseMedia:fail privacy authorization required', errno: 112 }) }), error => error.privacyRequired === true)
  await assert.rejects(chooseAvatarImage({ chooseMedia: () => { throw new Error('native failed') } }), /native failed/)
})

test('cancelled selection and empty media results never replace an avatar', async () => {
  await assert.rejects(chooseAvatarImage({ chooseMedia: options => options.fail({ errMsg: 'chooseMedia:fail cancel' }) }), error => error.cancelled === true)
  await assert.rejects(chooseAvatarImage({ chooseMedia: options => options.success({ tempFiles: [] }) }), /图片/)
})
